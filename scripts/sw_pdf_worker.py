#!/usr/bin/env python3
"""
Standalone Sedro-Woolley PDF ingestion worker.

What it does:
- Connects directly to Postgres via DATABASE_URL.
- Claims PDF rows from openskagit_sedrowoolleycrawldocument.
- Processes unique PDFs in parallel (deduped by source SHA256 when available).
- Writes artifacts under MEDIA_ROOT (default: /media):
  - document.md
  - document.json
  - chunks.jsonl
- Updates DB rows with output paths:
  - text_path -> document.md
  - raw_html_path -> document.json (metadata payload path)

Dependencies:
- psycopg
- requests
- pypdf
- optional OCR: pdf2image + pytesseract

Example:
  DATABASE_URL="postgresql://user:pass@db-host:5432/dbname?sslmode=require" \
  python3 scripts/sw_pdf_worker.py --media-root /media --workers 8 --batch-size 100
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import psycopg
import requests
from psycopg.rows import dict_row


TABLE_NAME = "openskagit_sedrowoolleycrawldocument"


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        return


def _sanitize_name(value: str) -> str:
    cleaned: list[str] = []
    for ch in (value or "").strip():
        if ch.isalnum() or ch in {".", "_", "-"}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    compact = "".join(cleaned).strip("._")
    return compact[:120] if compact else "item"


def _chunk_text(text: str, max_chars: int) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []

    paragraphs = [segment.strip() for segment in normalized.split("\n\n") if segment.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for paragraph in paragraphs:
        size = len(paragraph)
        if current and current_size + 2 + size > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_size = size
            continue

        if not current:
            current = [paragraph]
            current_size = size
            continue

        current.append(paragraph)
        current_size += 2 + size

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _extract_table_like_blocks(text: str) -> list[str]:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        compact = line.strip()
        has_columns = "  " in line or "\t" in line
        has_number = any(ch.isdigit() for ch in compact)
        if compact and has_columns and has_number:
            current.append(compact)
            continue

        if len(current) >= 2:
            blocks.append("\n".join(current))
        current = []

    if len(current) >= 2:
        blocks.append("\n".join(current))
    return blocks


def _render_markdown(payload: dict[str, Any]) -> str:
    title = payload.get("title") or Path(urlparse(payload.get("source_url") or "").path).name or "Document"
    lines = [
        f"# {title}",
        "",
        f"- Source URL: {payload.get('source_url') or ''}",
        f"- Source media path: {payload.get('source_media_path') or ''}",
        f"- Source SHA256: {payload.get('source_sha256') or ''}",
        f"- Processed at: {payload.get('processed_at') or ''}",
        f"- Pages: {payload.get('page_count') or 0}",
        f"- Extracted characters: {payload.get('text_chars') or 0}",
        f"- OCR pages: {payload.get('ocr_pages') or 0}",
        f"- Table-like blocks: {payload.get('table_block_count') or 0}",
        "",
        "## Pages",
        "",
    ]

    for page in payload.get("pages") or []:
        lines.append(f"### Page {page.get('page_number')}")
        lines.append(
            f"_Source: {page.get('text_source')} | chars: {page.get('char_count')} | "
            f"table blocks: {page.get('table_block_count')}_"
        )
        lines.append("")
        body = (page.get("text") or "").strip()
        lines.append(body if body else "_No extractable text on this page._")
        lines.append("")

        blocks = page.get("table_blocks") or []
        if blocks:
            lines.append("#### Table-Like Blocks")
            lines.append("")
            for idx, block in enumerate(blocks, start=1):
                lines.append(f"Table block {idx}:")
                lines.append("```text")
                lines.append(block)
                lines.append("```")
                lines.append("")

        ocr_note = (page.get("ocr_note") or "").strip()
        if ocr_note:
            lines.append(f"_OCR note: {ocr_note}_")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def _build_chunks(payload: dict[str, Any], chunk_chars: int) -> list[dict[str, Any]]:
    source_url = payload.get("source_url") or ""
    source_sha256 = payload.get("source_sha256") or hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    source_media_path = payload.get("source_media_path") or ""
    title = payload.get("title") or ""

    rows: list[dict[str, Any]] = []
    idx = 0
    for page in payload.get("pages") or []:
        page_number = int(page.get("page_number") or 0)
        for chunk in _chunk_text(page.get("text") or "", chunk_chars):
            idx += 1
            rows.append(
                {
                    "chunk_id": f"{source_sha256}-{idx}",
                    "source_url": source_url,
                    "source_sha256": source_sha256,
                    "source_media_path": source_media_path,
                    "title": title,
                    "page_number": page_number,
                    "text_source": page.get("text_source") or "text_layer",
                    "char_count": len(chunk),
                    "text": chunk,
                }
            )

        for table_idx, block in enumerate(page.get("table_blocks") or [], start=1):
            idx += 1
            rows.append(
                {
                    "chunk_id": f"{source_sha256}-table-{page_number}-{table_idx}",
                    "source_url": source_url,
                    "source_sha256": source_sha256,
                    "source_media_path": source_media_path,
                    "title": title,
                    "page_number": page_number,
                    "text_source": "table_candidate",
                    "char_count": len(block),
                    "text": block,
                }
            )

    return rows


@dataclass
class Job:
    id: int
    url: str
    media_path: str
    sha256: str
    title: str


@dataclass
class ExtractResult:
    ok: bool
    source_sha256: str
    md_rel_path: str
    json_rel_path: str
    chunks_rel_path: str
    page_count: int
    text_chars: int
    table_block_count: int
    ocr_pages: int
    error: str


def claim_jobs(
    conn: psycopg.Connection,
    *,
    batch_size: int,
    force: bool,
    retry_errors: bool,
    marker: str,
) -> list[Job]:
    where = "extension = '.pdf' AND (%(force)s OR COALESCE(text_path, '') = ''"
    if retry_errors:
        where += " OR text_path LIKE 'error:%'"
    where += ")"

    sql = f"""
    WITH candidates AS (
        SELECT id, url, media_path, COALESCE(sha256, '') AS sha256, COALESCE(title, '') AS title
        FROM {TABLE_NAME}
        WHERE {where}
        ORDER BY fetched_at DESC NULLS LAST, id DESC
        FOR UPDATE SKIP LOCKED
        LIMIT %(batch_size)s
    )
    UPDATE {TABLE_NAME} AS d
    SET text_path = %(marker)s
    FROM candidates c
    WHERE d.id = c.id
    RETURNING c.id, c.url, c.media_path, c.sha256, c.title;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql,
            {
                "force": force,
                "batch_size": batch_size,
                "marker": marker,
            },
        )
        rows = cur.fetchall()
    conn.commit()

    jobs: list[Job] = []
    for row in rows:
        jobs.append(
            Job(
                id=int(row["id"]),
                url=str(row["url"] or ""),
                media_path=str(row["media_path"] or ""),
                sha256=str(row["sha256"] or "").lower(),
                title=str(row["title"] or ""),
            )
        )
    return jobs


def finalize_rows(
    conn: psycopg.Connection,
    *,
    updates: list[tuple[str, str, int]],
) -> None:
    sql = f"UPDATE {TABLE_NAME} SET text_path = %s, raw_html_path = %s WHERE id = %s"
    with conn.cursor() as cur:
        cur.executemany(sql, updates)
    conn.commit()


def _default_source_key(job: Job) -> str:
    if job.sha256 and len(job.sha256) == 64:
        return job.sha256
    return hashlib.sha256(job.url.encode("utf-8")).hexdigest()


def _build_doc_dir(media_root: Path, prefix_root: Path, source_key: str) -> Path:
    return media_root / prefix_root / "docs" / "by_sha256" / source_key


def _download_pdf_to_temp(url: str, timeout_seconds: int) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="sw-pdf-", suffix=".pdf", delete=False)
    temp_path = Path(handle.name)
    handle.close()
    with requests.get(url, stream=True, timeout=timeout_seconds) as response:
        response.raise_for_status()
        with temp_path.open("wb") as out:
            for chunk in response.iter_content(chunk_size=1024 * 512):
                if not chunk:
                    continue
                out.write(chunk)
    return temp_path


def _maybe_extract_ocr(pdf_path: Path, page_number: int) -> tuple[str, str]:
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except Exception as exc:
        return "", f"OCR deps unavailable: {exc}"

    try:
        images = convert_from_path(str(pdf_path), first_page=page_number, last_page=page_number, fmt="png")
        if not images:
            return "", "OCR produced no image"
        return pytesseract.image_to_string(images[0]) or "", ""
    except Exception as exc:
        return "", f"OCR failed: {exc}"


def process_pdf(
    *,
    media_root: str,
    prefix_root: str,
    source_key: str,
    url: str,
    source_media_path: str,
    title: str,
    chunk_chars: int,
    timeout_seconds: int,
    download_missing: bool,
    enable_ocr: bool,
) -> ExtractResult:
    from pypdf import PdfReader

    media_root_path = Path(media_root)
    doc_dir = _build_doc_dir(media_root_path, Path(prefix_root), source_key)
    md_path = doc_dir / "document.md"
    json_path = doc_dir / "document.json"
    chunks_path = doc_dir / "chunks.jsonl"

    source_abs = media_root_path / source_media_path if source_media_path else Path()
    temp_download: Optional[Path] = None
    if not source_abs.exists():
        if not download_missing:
            return ExtractResult(
                ok=False,
                source_sha256=source_key,
                md_rel_path="",
                json_rel_path="",
                chunks_rel_path="",
                page_count=0,
                text_chars=0,
                table_block_count=0,
                ocr_pages=0,
                error=f"Missing source file: {source_abs}",
            )
        try:
            temp_download = _download_pdf_to_temp(url=url, timeout_seconds=timeout_seconds)
            source_abs = temp_download
        except Exception as exc:
            return ExtractResult(
                ok=False,
                source_sha256=source_key,
                md_rel_path="",
                json_rel_path="",
                chunks_rel_path="",
                page_count=0,
                text_chars=0,
                table_block_count=0,
                ocr_pages=0,
                error=f"Failed to download source PDF: {exc}",
            )

    try:
        reader = PdfReader(str(source_abs))
    except Exception as exc:
        if temp_download and temp_download.exists():
            temp_download.unlink(missing_ok=True)
        return ExtractResult(
            ok=False,
            source_sha256=source_key,
            md_rel_path="",
            json_rel_path="",
            chunks_rel_path="",
            page_count=0,
            text_chars=0,
            table_block_count=0,
            ocr_pages=0,
            error=f"Could not parse PDF: {exc}",
        )

    pages: list[dict[str, Any]] = []
    text_chars = 0
    table_block_count = 0
    ocr_pages = 0

    for page_number, page in enumerate(reader.pages, start=1):
        text = ""
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""

        source = "text_layer"
        ocr_note = ""
        if not text.strip() and enable_ocr:
            ocr_text, ocr_note = _maybe_extract_ocr(source_abs, page_number)
            if ocr_text.strip():
                text = ocr_text
                source = "ocr"
                ocr_pages += 1

        table_blocks = _extract_table_like_blocks(text)
        table_block_count += len(table_blocks)
        text_chars += len(text)
        pages.append(
            {
                "page_number": page_number,
                "char_count": len(text),
                "text_source": source,
                "ocr_note": ocr_note,
                "table_block_count": len(table_blocks),
                "table_blocks": table_blocks,
                "text": text,
            }
        )

    payload = {
        "source_url": url,
        "source_media_path": source_media_path,
        "source_sha256": source_key,
        "title": title,
        "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "page_count": len(pages),
        "text_chars": text_chars,
        "table_block_count": table_block_count,
        "ocr_pages": ocr_pages,
        "pages": pages,
    }
    markdown = _render_markdown(payload)
    chunks = _build_chunks(payload, chunk_chars=chunk_chars)

    doc_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    with chunks_path.open("w", encoding="utf-8") as handle:
        for row in chunks:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    if temp_download and temp_download.exists():
        temp_download.unlink(missing_ok=True)

    return ExtractResult(
        ok=True,
        source_sha256=source_key,
        md_rel_path=str(md_path.relative_to(media_root_path)).replace("\\", "/"),
        json_rel_path=str(json_path.relative_to(media_root_path)).replace("\\", "/"),
        chunks_rel_path=str(chunks_path.relative_to(media_root_path)).replace("\\", "/"),
        page_count=len(pages),
        text_chars=text_chars,
        table_block_count=table_block_count,
        ocr_pages=ocr_pages,
        error="",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone Sedro-Woolley PDF worker")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--media-root", default=os.getenv("MEDIA_ROOT", "/media"))
    parser.add_argument("--workers", type=int, default=max((os.cpu_count() or 4) // 2, 2))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-docs", type=int, default=0, help="0 means no explicit limit")
    parser.add_argument("--force", action="store_true", help="Reprocess even if text_path already set.")
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Allow reprocessing rows with text_path starting with error:.",
    )
    parser.add_argument("--download-missing", action="store_true", help="Download missing PDFs by URL.")
    parser.add_argument("--chunk-chars", type=int, default=1800)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument(
        "--prefix",
        default="sedro_woolley/pdf_ingest_worker",
        help="Relative output prefix under media root.",
    )
    return parser.parse_args()


def main() -> int:
    _load_dotenv_if_available()
    args = parse_args()

    if not args.database_url:
        print("ERROR: DATABASE_URL is required (pass --database-url or set env var).")
        return 1
    if args.workers < 1:
        print("ERROR: --workers must be at least 1.")
        return 1
    if args.batch_size < 1:
        print("ERROR: --batch-size must be at least 1.")
        return 1
    if args.chunk_chars < 300:
        print("ERROR: --chunk-chars must be at least 300.")
        return 1

    media_root = Path(args.media_root).expanduser().resolve()
    prefix_root = Path(args.prefix)
    manifest_root = media_root / prefix_root / "manifests"
    runs_root = media_root / prefix_root / "runs"
    manifest_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    run_started = dt.datetime.now(dt.timezone.utc)
    run_id = run_started.strftime("%Y%m%dT%H%M%SZ")
    hostname = socket.gethostname()
    pid = os.getpid()
    marker = f"processing:{time.time()}:{hostname}:{pid}:{run_id}"
    manifest_path = manifest_root / f"{run_id}.jsonl"
    summary_path = runs_root / f"{run_id}.json"

    total_claimed = 0
    total_processed = 0
    total_success = 0
    total_failed = 0
    total_reused = 0
    failures: list[dict[str, Any]] = []

    started_clock = time.monotonic()
    with psycopg.connect(args.database_url, row_factory=dict_row) as conn, manifest_path.open(
        "w", encoding="utf-8"
    ) as manifest:
        while True:
            if args.max_docs and total_processed >= args.max_docs:
                break

            remaining = args.max_docs - total_processed if args.max_docs else args.batch_size
            batch_size = min(args.batch_size, remaining) if args.max_docs else args.batch_size

            jobs = claim_jobs(
                conn,
                batch_size=batch_size,
                force=args.force,
                retry_errors=args.retry_errors,
                marker=marker,
            )
            if not jobs:
                break

            total_claimed += len(jobs)

            by_key: dict[str, list[Job]] = {}
            representative: dict[str, Job] = {}
            for job in jobs:
                key = _default_source_key(job)
                by_key.setdefault(key, []).append(job)
                representative.setdefault(key, job)

            result_by_key: dict[str, ExtractResult] = {}
            futures = {}
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                for key, rep in representative.items():
                    doc_dir = _build_doc_dir(media_root, prefix_root, key)
                    md_path = doc_dir / "document.md"
                    json_path = doc_dir / "document.json"
                    chunks_path = doc_dir / "chunks.jsonl"
                    if not args.force and md_path.exists() and json_path.exists() and chunks_path.exists():
                        total_reused += 1
                        result_by_key[key] = ExtractResult(
                            ok=True,
                            source_sha256=key,
                            md_rel_path=str(md_path.relative_to(media_root)).replace("\\", "/"),
                            json_rel_path=str(json_path.relative_to(media_root)).replace("\\", "/"),
                            chunks_rel_path=str(chunks_path.relative_to(media_root)).replace("\\", "/"),
                            page_count=0,
                            text_chars=0,
                            table_block_count=0,
                            ocr_pages=0,
                            error="",
                        )
                        continue

                    futures[
                        pool.submit(
                            process_pdf,
                            media_root=str(media_root),
                            prefix_root=str(prefix_root),
                            source_key=key,
                            url=rep.url,
                            source_media_path=rep.media_path,
                            title=rep.title,
                            chunk_chars=args.chunk_chars,
                            timeout_seconds=args.timeout_seconds,
                            download_missing=args.download_missing,
                            enable_ocr=args.enable_ocr,
                        )
                    ] = key

                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        result_by_key[key] = future.result()
                    except Exception as exc:  # pragma: no cover - worker boundary
                        result_by_key[key] = ExtractResult(
                            ok=False,
                            source_sha256=key,
                            md_rel_path="",
                            json_rel_path="",
                            chunks_rel_path="",
                            page_count=0,
                            text_chars=0,
                            table_block_count=0,
                            ocr_pages=0,
                            error=f"Worker failure: {exc}",
                        )

            updates: list[tuple[str, str, int]] = []
            for key, jobs_for_key in by_key.items():
                result = result_by_key[key]
                for job in jobs_for_key:
                    total_processed += 1
                    row = {
                        "run_id": run_id,
                        "job_id": job.id,
                        "source_key": key,
                        "url": job.url,
                        "source_media_path": job.media_path,
                        "ok": result.ok,
                        "md_rel_path": result.md_rel_path,
                        "json_rel_path": result.json_rel_path,
                        "chunks_rel_path": result.chunks_rel_path,
                        "page_count": result.page_count,
                        "text_chars": result.text_chars,
                        "table_block_count": result.table_block_count,
                        "ocr_pages": result.ocr_pages,
                        "error": result.error,
                        "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }
                    manifest.write(json.dumps(row, ensure_ascii=True) + "\n")

                    if result.ok:
                        total_success += 1
                        updates.append((result.md_rel_path, result.json_rel_path, job.id))
                    else:
                        total_failed += 1
                        error_token = f"error:{int(time.time())}"
                        error_note = (result.error or "unknown error")[:790]
                        updates.append((error_token, error_note, job.id))
                        failures.append({"id": job.id, "url": job.url, "error": result.error})

            finalize_rows(conn, updates=updates)

    run_finished = dt.datetime.now(dt.timezone.utc)
    summary = {
        "run_id": run_id,
        "started_at": run_started.isoformat(),
        "finished_at": run_finished.isoformat(),
        "duration_seconds": round(time.monotonic() - started_clock, 2),
        "database_host": urlparse(args.database_url).hostname or "",
        "media_root": str(media_root),
        "prefix": args.prefix,
        "workers": args.workers,
        "batch_size": args.batch_size,
        "max_docs": args.max_docs,
        "force": args.force,
        "retry_errors": args.retry_errors,
        "download_missing": args.download_missing,
        "enable_ocr": args.enable_ocr,
        "chunk_chars": args.chunk_chars,
        "claimed_rows": total_claimed,
        "processed_rows": total_processed,
        "success_rows": total_success,
        "failed_rows": total_failed,
        "reused_artifacts": total_reused,
        "manifest_path": str(manifest_path.relative_to(media_root)).replace("\\", "/"),
        "run_summary_path": str(summary_path.relative_to(media_root)).replace("\\", "/"),
        "failures": failures[:200],
    }

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    shutil.copyfile(manifest_path, manifest_root / "latest.jsonl")
    shutil.copyfile(summary_path, runs_root / "latest.json")

    print("Sedro-Woolley PDF worker completed.")
    print(f"run_id: {run_id}")
    print(f"claimed_rows: {total_claimed}")
    print(f"processed_rows: {total_processed}")
    print(f"success_rows: {total_success}")
    print(f"failed_rows: {total_failed}")
    print(f"reused_artifacts: {total_reused}")
    print(f"manifest_path: {summary['manifest_path']}")
    print(f"run_summary_path: {summary['run_summary_path']}")
    return 0 if total_failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
