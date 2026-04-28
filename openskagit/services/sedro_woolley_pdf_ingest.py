from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from django.db import OperationalError, ProgrammingError

from openskagit.services.sedro_woolley_crawl import normalize_url


LOGGER = logging.getLogger(__name__)


def _sanitize_name(value: str) -> str:
    cleaned = []
    for char in (value or "").strip():
        if char.isalnum() or char in {".", "_", "-"}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    compact = "".join(cleaned).strip("._")
    return compact[:120] if compact else "item"


def _rel_media_path(path: Path, media_root: Path) -> str:
    return str(path.relative_to(media_root)).replace("\\", "/")


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
        condensed = line.strip()
        has_columns = "  " in line or "\t" in line
        has_digits = any(ch.isdigit() for ch in condensed)
        if condensed and has_columns and has_digits:
            current.append(condensed)
            continue

        if len(current) >= 2:
            blocks.append("\n".join(current))
        current = []

    if len(current) >= 2:
        blocks.append("\n".join(current))

    return blocks


def find_sw_pdf_source_records(
    *,
    media_root: Path,
    run_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    records = _load_pdf_records_from_db(run_id=run_id, limit=limit)
    if records:
        return records
    return _load_pdf_records_from_manifest(media_root=media_root, run_id=run_id, limit=limit)


def _load_pdf_records_from_db(*, run_id: Optional[str], limit: Optional[int]) -> list[dict[str, Any]]:
    try:
        from openskagit.models import SedroWoolleyCrawlDocument, SedroWoolleyCrawlRun
    except Exception:
        return []

    try:
        if run_id:
            run_row = SedroWoolleyCrawlRun.objects.filter(run_id=run_id).first()
        else:
            run_row = SedroWoolleyCrawlRun.objects.order_by("-started_at").first()
    except (OperationalError, ProgrammingError):
        return []

    if not run_row:
        return []

    queryset = SedroWoolleyCrawlDocument.objects.filter(run=run_row).order_by("-fetched_at")
    queryset = queryset.filter(extension__iexact=".pdf")
    if limit:
        queryset = queryset[:limit]

    records: list[dict[str, Any]] = []
    for row in queryset:
        if not row.media_path:
            continue
        records.append(
            {
                "url": row.url,
                "title": row.title or "",
                "media_path": row.media_path,
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else "",
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "content_type": row.content_type,
                "source": "db",
            }
        )

    return records


def _load_pdf_records_from_manifest(
    *,
    media_root: Path,
    run_id: Optional[str],
    limit: Optional[int],
) -> list[dict[str, Any]]:
    root = media_root / "sedro_woolley" / "manifests"
    if run_id:
        manifest_path = root / f"{run_id}.jsonl"
    else:
        manifest_path = root / "latest.jsonl"

    if not manifest_path.exists():
        return []

    seen_urls: set[str] = set()
    records: list[dict[str, Any]] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        extension = str(row.get("extension") or "").lower()
        content_type = str(row.get("content_type") or "").lower()
        url = normalize_url(str(row.get("url") or "")) or str(row.get("url") or "")
        if not url:
            continue
        if extension != ".pdf" and "application/pdf" not in content_type and not url.lower().endswith(".pdf"):
            continue
        if url in seen_urls:
            continue

        media_path = row.get("media_path") or ""
        if not media_path:
            continue

        seen_urls.add(url)
        records.append(
            {
                "url": url,
                "title": row.get("title") or "",
                "media_path": media_path,
                "fetched_at": row.get("fetched_at") or "",
                "sha256": row.get("sha256") or "",
                "size_bytes": row.get("size_bytes") or 0,
                "content_type": row.get("content_type") or "",
                "source": "manifest",
            }
        )

        if limit and len(records) >= limit:
            break

    return records


@dataclass
class PdfIngestSummary:
    run_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    source_run_id: str
    records_found: int
    processed_count: int
    success_count: int
    dry_run_count: int
    skipped_count: int
    failed_count: int
    workers: int
    resume: bool
    force: bool
    dry_run: bool
    enable_ocr: bool
    ocr_available: bool
    extract_tables: bool
    table_engine: str
    chunks_written: int
    chunks_path: str
    manifest_path: str
    run_summary_path: str
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "source_run_id": self.source_run_id,
            "records_found": self.records_found,
            "processed_count": self.processed_count,
            "success_count": self.success_count,
            "dry_run_count": self.dry_run_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "workers": self.workers,
            "resume": self.resume,
            "force": self.force,
            "dry_run": self.dry_run,
            "enable_ocr": self.enable_ocr,
            "ocr_available": self.ocr_available,
            "extract_tables": self.extract_tables,
            "table_engine": self.table_engine,
            "chunks_written": self.chunks_written,
            "chunks_path": self.chunks_path,
            "manifest_path": self.manifest_path,
            "run_summary_path": self.run_summary_path,
            "failures": self.failures,
        }


class SedroWoolleyPdfIngestor:
    def __init__(
        self,
        *,
        media_root: Path,
        workers: int = 4,
        resume: bool = True,
        force: bool = False,
        dry_run: bool = False,
        enable_ocr: bool = False,
        extract_tables: bool = True,
        chunk_chars: int = 1800,
    ) -> None:
        self.media_root = media_root
        self.root = media_root / "sedro_woolley"
        self.output_root = self.root / "pdf_ingest"
        self.docs_markdown_root = self.output_root / "markdown"
        self.docs_json_root = self.output_root / "documents"
        self.chunks_root = self.output_root / "chunks"
        self.manifests_root = self.output_root / "manifests"
        self.runs_root = self.output_root / "runs"

        self.workers = max(1, workers)
        self.resume = resume
        self.force = force
        self.dry_run = dry_run
        self.enable_ocr = enable_ocr
        self.extract_tables = extract_tables
        self.chunk_chars = max(300, chunk_chars)

        self._ocr_available = False
        self._ocr_error = ""
        if self.enable_ocr:
            try:
                import pdf2image  # noqa: F401
                import pytesseract  # noqa: F401

                self._ocr_available = True
            except Exception as exc:  # pragma: no cover - environment-dependent
                self._ocr_error = str(exc)

        self._table_engine = "heuristic"
        self._camelot = None
        if self.extract_tables:
            try:
                import camelot

                self._camelot = camelot
                self._table_engine = "camelot"
            except Exception:
                self._table_engine = "heuristic"

    def ingest(
        self,
        *,
        run_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> PdfIngestSummary:
        start_clock = time.monotonic()
        started_at = dt.datetime.now(dt.timezone.utc)
        ingest_run_id = started_at.strftime("%Y%m%dT%H%M%SZ")

        self.docs_markdown_root.mkdir(parents=True, exist_ok=True)
        self.docs_json_root.mkdir(parents=True, exist_ok=True)
        self.chunks_root.mkdir(parents=True, exist_ok=True)
        self.manifests_root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)

        source_records = find_sw_pdf_source_records(
            media_root=self.media_root,
            run_id=run_id,
            limit=limit,
        )

        manifest_path = self.manifests_root / f"{ingest_run_id}.jsonl"
        run_chunks_path = self.chunks_root / f"{ingest_run_id}.jsonl"
        summary_path = self.runs_root / f"{ingest_run_id}.json"
        run_chunks_rel = _rel_media_path(run_chunks_path, self.media_root)
        source_run_id = run_id or "latest"

        failures: list[dict[str, Any]] = []
        success_count = 0
        skipped_count = 0
        failed_count = 0
        processed_count = 0
        dry_run_count = 0
        chunks_written = 0

        futures = {}
        with manifest_path.open("w", encoding="utf-8") as manifest_handle, run_chunks_path.open(
            "w", encoding="utf-8"
        ) as run_chunks_handle:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                for record in source_records:
                    artifact_paths = self._build_artifact_paths(record)
                    entry = {
                        "url": record.get("url") or "",
                        "media_path": record.get("media_path") or "",
                        "source_key": artifact_paths["source_key"],
                        "source_sha256": record.get("sha256") or "",
                        "source": record.get("source") or "",
                        "document_json_path": _rel_media_path(artifact_paths["json"], self.media_root),
                        "document_md_path": _rel_media_path(artifact_paths["md"], self.media_root),
                        "chunks_path": run_chunks_rel,
                        "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }

                    should_skip = self.resume and artifact_paths["json"].exists() and not self.force
                    if should_skip:
                        skipped_count += 1
                        entry.update(
                            {
                                "status": "skipped",
                                "error": "",
                                "page_count": 0,
                                "text_chars": 0,
                                "table_count": 0,
                                "ocr_pages": 0,
                                "chunk_count": 0,
                            }
                        )
                        manifest_handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
                        continue

                    if self.dry_run:
                        processed_count += 1
                        dry_run_count += 1
                        entry.update(
                            {
                                "status": "dry_run",
                                "error": "",
                                "page_count": 0,
                                "text_chars": 0,
                                "table_count": 0,
                                "ocr_pages": 0,
                                "chunk_count": 0,
                            }
                        )
                        manifest_handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
                        continue

                    future = executor.submit(self._process_pdf_record, record, artifact_paths)
                    futures[future] = entry

                for future in as_completed(futures):
                    entry = futures[future]
                    processed_count += 1
                    try:
                        result = future.result()
                    except Exception as exc:  # pragma: no cover - defensive worker boundary
                        result = {
                            "status": "failed",
                            "error": str(exc),
                            "page_count": 0,
                            "text_chars": 0,
                            "table_count": 0,
                            "ocr_pages": 0,
                            "chunk_count": 0,
                            "chunk_rows": [],
                        }

                    if result["status"] == "success":
                        success_count += 1
                        for chunk_row in result.get("chunk_rows") or []:
                            run_chunks_handle.write(json.dumps(chunk_row, ensure_ascii=True) + "\n")
                            chunks_written += 1
                    else:
                        failed_count += 1
                        failures.append(
                            {
                                "url": entry.get("url") or "",
                                "media_path": entry.get("media_path") or "",
                                "error": result.get("error") or "unknown error",
                            }
                        )

                    entry.update(result)
                    entry.pop("chunk_rows", None)
                    entry["processed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    manifest_handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

        finished_at = dt.datetime.now(dt.timezone.utc)
        duration = round(time.monotonic() - start_clock, 2)

        summary = PdfIngestSummary(
            run_id=ingest_run_id,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=duration,
            source_run_id=source_run_id,
            records_found=len(source_records),
            processed_count=processed_count,
            success_count=success_count,
            dry_run_count=dry_run_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            workers=self.workers,
            resume=self.resume,
            force=self.force,
            dry_run=self.dry_run,
            enable_ocr=self.enable_ocr,
            ocr_available=self._ocr_available,
            extract_tables=self.extract_tables,
            table_engine=self._table_engine,
            chunks_written=chunks_written,
            chunks_path=run_chunks_rel,
            manifest_path=_rel_media_path(manifest_path, self.media_root),
            run_summary_path=_rel_media_path(summary_path, self.media_root),
            failures=failures,
        )

        summary_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
        shutil.copyfile(run_chunks_path, self.chunks_root / "latest.jsonl")
        shutil.copyfile(manifest_path, self.manifests_root / "latest.jsonl")
        shutil.copyfile(summary_path, self.runs_root / "latest.json")

        return summary

    def _build_artifact_paths(self, record: dict[str, Any]) -> dict[str, Path]:
        source_key = self._build_source_key(record)
        return {
            "source_key": source_key,
            "json": self.docs_json_root / f"{source_key}.json",
            "md": self.docs_markdown_root / f"{source_key}.md",
        }

    def _build_source_key(self, record: dict[str, Any]) -> str:
        sha = str(record.get("sha256") or "").strip().lower()
        if len(sha) == 64 and all(ch in "0123456789abcdef" for ch in sha):
            return sha

        url = normalize_url(record.get("url") or "") or str(record.get("url") or "")
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def _process_pdf_record(self, record: dict[str, Any], artifact_paths: dict[str, Path]) -> dict[str, Any]:
        source_rel_path = record.get("media_path") or ""
        source_abs_path = self.media_root / source_rel_path
        if not source_abs_path.exists():
            return {
                "status": "failed",
                "error": f"source file missing: {source_abs_path}",
                "page_count": 0,
                "text_chars": 0,
                "table_count": 0,
                "ocr_pages": 0,
            }

        try:
            from pypdf import PdfReader
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"pypdf not available: {exc}",
                "page_count": 0,
                "text_chars": 0,
                "table_count": 0,
                "ocr_pages": 0,
            }

        try:
            reader = PdfReader(str(source_abs_path))
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"could not parse PDF: {exc}",
                "page_count": 0,
                "text_chars": 0,
                "table_count": 0,
                "ocr_pages": 0,
            }

        page_payloads: list[dict[str, Any]] = []
        total_text_chars = 0
        total_table_count = 0
        total_ocr_pages = 0

        for idx, page in enumerate(reader.pages, start=1):
            extracted_text = ""
            try:
                extracted_text = page.extract_text() or ""
            except Exception:
                extracted_text = ""

            text_source = "text_layer"
            ocr_note = ""

            if not extracted_text.strip() and self.enable_ocr:
                if self._ocr_available:
                    ocr_text, ocr_note = self._run_ocr(source_abs_path, idx)
                    if ocr_text.strip():
                        extracted_text = ocr_text
                        text_source = "ocr"
                        total_ocr_pages += 1
                else:
                    ocr_note = self._ocr_error or "OCR dependencies unavailable"

            table_blocks = _extract_table_like_blocks(extracted_text)

            page_payloads.append(
                {
                    "page_number": idx,
                    "char_count": len(extracted_text),
                    "text_source": text_source,
                    "ocr_note": ocr_note,
                    "table_block_count": len(table_blocks),
                    "table_blocks": table_blocks,
                    "text": extracted_text,
                }
            )
            total_text_chars += len(extracted_text)
            total_table_count += len(table_blocks)

        camelot_tables = []
        if self.extract_tables and self._camelot is not None:
            try:
                table_set = self._camelot.read_pdf(str(source_abs_path), pages="all", flavor="stream")
                for idx, table in enumerate(table_set, start=1):
                    try:
                        rows = table.df.fillna("").values.tolist()
                    except Exception:
                        rows = []
                    if rows:
                        camelot_tables.append(
                            {
                                "table_index": idx,
                                "page": table.page,
                                "rows": rows,
                            }
                        )
                if camelot_tables:
                    total_table_count += len(camelot_tables)
            except Exception as exc:
                LOGGER.warning("Camelot table extraction failed for %s: %s", source_abs_path, exc)

        document_payload = {
            "source_url": record.get("url") or "",
            "title": record.get("title") or "",
            "source_media_path": source_rel_path,
            "source_sha256": record.get("sha256") or "",
            "source_size_bytes": record.get("size_bytes") or 0,
            "source_content_type": record.get("content_type") or "",
            "fetched_at": record.get("fetched_at") or "",
            "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "page_count": len(page_payloads),
            "text_chars": total_text_chars,
            "ocr_pages": total_ocr_pages,
            "table_count": total_table_count,
            "table_engine": self._table_engine,
            "ocr_enabled": self.enable_ocr,
            "ocr_available": self._ocr_available,
            "pages": page_payloads,
            "tables": camelot_tables,
        }

        markdown_output = self._render_markdown(document_payload)
        chunk_rows = self._build_chunk_rows(document_payload)

        artifact_paths["json"].parent.mkdir(parents=True, exist_ok=True)
        artifact_paths["md"].parent.mkdir(parents=True, exist_ok=True)
        artifact_paths["json"].write_text(json.dumps(document_payload, indent=2), encoding="utf-8")
        artifact_paths["md"].write_text(markdown_output, encoding="utf-8")

        return {
            "status": "success",
            "error": "",
            "page_count": len(page_payloads),
            "text_chars": total_text_chars,
            "table_count": total_table_count,
            "ocr_pages": total_ocr_pages,
            "chunk_count": len(chunk_rows),
            "chunk_rows": chunk_rows,
        }

    def _run_ocr(self, pdf_path: Path, page_number: int) -> tuple[str, str]:
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except Exception as exc:  # pragma: no cover - environment-dependent
            return "", str(exc)

        try:
            images = convert_from_path(
                str(pdf_path),
                first_page=page_number,
                last_page=page_number,
                fmt="png",
            )
            if not images:
                return "", "no image rendered"
            text = pytesseract.image_to_string(images[0])
            return text or "", ""
        except Exception as exc:  # pragma: no cover - environment-dependent
            return "", str(exc)

    def _render_markdown(self, payload: dict[str, Any]) -> str:
        source_url = payload.get("source_url") or ""
        title = payload.get("title") or ""
        page_count = payload.get("page_count") or 0
        text_chars = payload.get("text_chars") or 0
        table_count = payload.get("table_count") or 0

        lines = [
            f"# {title or Path(urlparse(source_url).path).name or 'Document'}",
            "",
            f"- Source URL: {source_url}",
            f"- Source media path: {payload.get('source_media_path') or ''}",
            f"- Source SHA256: {payload.get('source_sha256') or ''}",
            f"- Fetched at: {payload.get('fetched_at') or ''}",
            f"- Processed at: {payload.get('processed_at') or ''}",
            f"- Pages: {page_count}",
            f"- Extracted characters: {text_chars}",
            f"- Table blocks: {table_count}",
            f"- OCR enabled: {payload.get('ocr_enabled')}",
            f"- OCR available: {payload.get('ocr_available')}",
            "",
        ]

        tables = payload.get("tables") or []
        if tables:
            lines.extend(["## Tables (Camelot)", ""])
            for table in tables:
                lines.append(f"### Table {table.get('table_index')} (page {table.get('page')})")
                rows = table.get("rows") or []
                if not rows:
                    lines.append("_No rows parsed._")
                    lines.append("")
                    continue

                header = rows[0]
                lines.append("| " + " | ".join(cell.strip() for cell in header) + " |")
                lines.append("| " + " | ".join("---" for _ in header) + " |")
                for row in rows[1:]:
                    lines.append("| " + " | ".join(cell.strip() for cell in row) + " |")
                lines.append("")

        lines.extend(["## Pages", ""])
        for page in payload.get("pages") or []:
            page_number = page.get("page_number")
            lines.append(f"### Page {page_number}")
            lines.append(
                f"_Source: {page.get('text_source')} | chars: {page.get('char_count')} | "
                f"table blocks: {page.get('table_block_count')}_"
            )
            lines.append("")
            page_text = (page.get("text") or "").strip()
            if page_text:
                lines.append(page_text)
            else:
                lines.append("_No extractable text on this page._")
            lines.append("")

            table_blocks = page.get("table_blocks") or []
            if table_blocks:
                lines.append("#### Table-Like Blocks")
                lines.append("")
                for idx, block in enumerate(table_blocks, start=1):
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

    def _build_chunk_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        chunk_rows: list[dict[str, Any]] = []
        source_url = payload.get("source_url") or ""
        source_media_path = payload.get("source_media_path") or ""
        source_sha256 = payload.get("source_sha256") or ""
        title = payload.get("title") or ""

        chunk_index = 0
        for page in payload.get("pages") or []:
            page_number = int(page.get("page_number") or 0)
            text = page.get("text") or ""
            for text_chunk in _chunk_text(text, self.chunk_chars):
                chunk_index += 1
                chunk_rows.append(
                    {
                        "chunk_id": f"{source_sha256 or hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:16]}-{chunk_index}",
                        "source_url": source_url,
                        "source_media_path": source_media_path,
                        "source_sha256": source_sha256,
                        "title": title,
                        "page_number": page_number,
                        "text_source": page.get("text_source") or "text_layer",
                        "char_count": len(text_chunk),
                        "text": text_chunk,
                    }
                )

            table_blocks = page.get("table_blocks") or []
            for table_index, block in enumerate(table_blocks, start=1):
                chunk_index += 1
                chunk_rows.append(
                    {
                        "chunk_id": f"{source_sha256 or hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:16]}-table-{page_number}-{table_index}",
                        "source_url": source_url,
                        "source_media_path": source_media_path,
                        "source_sha256": source_sha256,
                        "title": title,
                        "page_number": page_number,
                        "text_source": "table_candidate",
                        "char_count": len(block),
                        "text": block,
                    }
                )

        tables = payload.get("tables") or []
        for idx, table in enumerate(tables, start=1):
            chunk_index += 1
            rows = table.get("rows") or []
            flat = "\n".join([" | ".join(str(cell).strip() for cell in row) for row in rows if row]).strip()
            if not flat:
                continue
            chunk_rows.append(
                {
                    "chunk_id": f"{source_sha256 or hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:16]}-camelot-{idx}",
                    "source_url": source_url,
                    "source_media_path": source_media_path,
                    "source_sha256": source_sha256,
                    "title": title,
                    "page_number": int(table.get("page") or 0),
                    "text_source": "camelot_table",
                    "char_count": len(flat),
                    "text": flat,
                }
            )

        return chunk_rows
