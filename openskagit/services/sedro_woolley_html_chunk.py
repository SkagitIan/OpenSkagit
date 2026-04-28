from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from django.db import OperationalError, ProgrammingError

from openskagit.services.sedro_woolley_crawl import normalize_url


def _rel_media_path(path: Path, media_root: Path) -> str:
    return str(path.relative_to(media_root)).replace("\\", "/")


def _chunk_text(text: str, max_chars: int) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []

    paragraphs = [segment.strip() for segment in normalized.split("\n\n") if segment.strip()]
    expanded_paragraphs: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            expanded_paragraphs.append(paragraph)
            continue

        start = 0
        while start < len(paragraph):
            piece = paragraph[start : start + max_chars].strip()
            if piece:
                expanded_paragraphs.append(piece)
            start += max_chars

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for paragraph in expanded_paragraphs:
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


def _build_source_key(record: dict[str, Any]) -> str:
    sha = str(record.get("sha256") or "").strip().lower()
    if len(sha) == 64 and all(ch in "0123456789abcdef" for ch in sha):
        return sha

    url = normalize_url(record.get("url") or "") or str(record.get("url") or "")
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def find_sw_html_source_records(
    *,
    media_root: Path,
    run_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    records = _load_html_records_from_db(run_id=run_id, limit=limit)
    if records:
        return records
    return _load_html_records_from_manifest(media_root=media_root, run_id=run_id, limit=limit)


def _load_html_records_from_db(*, run_id: Optional[str], limit: Optional[int]) -> list[dict[str, Any]]:
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
    queryset = queryset.filter(resource_type="html_page")
    if limit:
        queryset = queryset[:limit]

    records: list[dict[str, Any]] = []
    for row in queryset:
        if not row.text_path:
            continue
        records.append(
            {
                "url": row.url,
                "title": row.title or "",
                "text_path": row.text_path,
                "sha256": row.sha256,
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else "",
                "source": "db",
            }
        )

    return records


def _load_html_records_from_manifest(
    *,
    media_root: Path,
    run_id: Optional[str],
    limit: Optional[int],
) -> list[dict[str, Any]]:
    root = media_root / "sedro_woolley" / "manifests"
    manifest_path = root / f"{run_id}.jsonl" if run_id else root / "latest.jsonl"
    if not manifest_path.exists():
        return []

    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        resource_type = str(row.get("resource_type") or "")
        extension = str(row.get("extension") or "").lower()
        if resource_type != "html_page" and extension != ".html":
            continue

        url = normalize_url(str(row.get("url") or "")) or str(row.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        text_path = str(row.get("text_path") or "").strip()
        if not text_path:
            continue

        records.append(
            {
                "url": url,
                "title": row.get("title") or "",
                "text_path": text_path,
                "sha256": row.get("sha256") or "",
                "fetched_at": row.get("fetched_at") or "",
                "source": "manifest",
            }
        )
        if limit and len(records) >= limit:
            break

    return records


@dataclass
class HtmlChunkSummary:
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
    chunk_chars: int
    min_chunk_chars: int
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
            "chunk_chars": self.chunk_chars,
            "min_chunk_chars": self.min_chunk_chars,
            "chunks_written": self.chunks_written,
            "chunks_path": self.chunks_path,
            "manifest_path": self.manifest_path,
            "run_summary_path": self.run_summary_path,
            "failures": self.failures,
        }


class SedroWoolleyHtmlChunker:
    def __init__(
        self,
        *,
        media_root: Path,
        workers: int = 4,
        resume: bool = True,
        force: bool = False,
        dry_run: bool = False,
        chunk_chars: int = 1800,
        min_chunk_chars: int = 80,
    ) -> None:
        self.media_root = media_root
        self.root = media_root / "sedro_woolley"
        self.output_root = self.root / "html_ingest"
        self.chunks_root = self.output_root / "chunks"
        self.manifests_root = self.output_root / "manifests"
        self.runs_root = self.output_root / "runs"

        self.workers = max(1, workers)
        self.resume = resume
        self.force = force
        self.dry_run = dry_run
        self.chunk_chars = max(300, chunk_chars)
        self.min_chunk_chars = max(1, min_chunk_chars)

    def chunk(
        self,
        *,
        run_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> HtmlChunkSummary:
        started_at_dt = dt.datetime.now(dt.timezone.utc)
        started_at = started_at_dt.isoformat()
        run_id_out = started_at_dt.strftime("%Y%m%dT%H%M%SZ")
        start_clock = time.monotonic()

        self.chunks_root.mkdir(parents=True, exist_ok=True)
        self.manifests_root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)

        source_records = find_sw_html_source_records(media_root=self.media_root, run_id=run_id, limit=limit)
        source_run_id = run_id or "latest"

        processed_keys = self._load_processed_source_keys() if self.resume and not self.force else set()

        manifest_path = self.manifests_root / f"{run_id_out}.jsonl"
        chunks_path = self.chunks_root / f"{run_id_out}.jsonl"
        summary_path = self.runs_root / f"{run_id_out}.json"
        chunks_rel = _rel_media_path(chunks_path, self.media_root)

        success_count = 0
        skipped_count = 0
        failed_count = 0
        processed_count = 0
        dry_run_count = 0
        chunks_written = 0
        failures: list[dict[str, Any]] = []

        futures = {}
        with manifest_path.open("w", encoding="utf-8") as manifest_handle, chunks_path.open(
            "w", encoding="utf-8"
        ) as chunks_handle:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                for record in source_records:
                    source_key = _build_source_key(record)
                    text_rel_path = str(record.get("text_path") or "").strip()
                    entry = {
                        "source_key": source_key,
                        "url": record.get("url") or "",
                        "title": record.get("title") or "",
                        "text_path": text_rel_path,
                        "source_sha256": record.get("sha256") or "",
                        "source": record.get("source") or "",
                        "chunks_path": chunks_rel,
                        "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }

                    should_skip = source_key in processed_keys
                    if should_skip:
                        skipped_count += 1
                        entry.update(
                            {
                                "status": "skipped",
                                "error": "",
                                "chunk_count": 0,
                                "text_chars": 0,
                            }
                        )
                        manifest_handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
                        continue

                    if self.dry_run:
                        dry_run_count += 1
                        processed_count += 1
                        entry.update(
                            {
                                "status": "dry_run",
                                "error": "",
                                "chunk_count": 0,
                                "text_chars": 0,
                            }
                        )
                        manifest_handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
                        continue

                    future = executor.submit(self._chunk_one_record, record, source_key)
                    futures[future] = entry

                for future in as_completed(futures):
                    processed_count += 1
                    entry = futures[future]

                    try:
                        result = future.result()
                    except Exception as exc:  # pragma: no cover
                        result = {
                            "status": "failed",
                            "error": str(exc),
                            "chunk_count": 0,
                            "text_chars": 0,
                            "chunk_rows": [],
                        }

                    if result.get("status") == "success":
                        success_count += 1
                        for chunk_row in result.get("chunk_rows") or []:
                            chunks_handle.write(json.dumps(chunk_row, ensure_ascii=True) + "\n")
                            chunks_written += 1
                    else:
                        failed_count += 1
                        failures.append(
                            {
                                "url": entry.get("url") or "",
                                "text_path": entry.get("text_path") or "",
                                "error": result.get("error") or "unknown error",
                            }
                        )

                    entry.update(result)
                    entry.pop("chunk_rows", None)
                    entry["processed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    manifest_handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

        finished_at_dt = dt.datetime.now(dt.timezone.utc)
        summary = HtmlChunkSummary(
            run_id=run_id_out,
            started_at=started_at,
            finished_at=finished_at_dt.isoformat(),
            duration_seconds=round(time.monotonic() - start_clock, 2),
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
            chunk_chars=self.chunk_chars,
            min_chunk_chars=self.min_chunk_chars,
            chunks_written=chunks_written,
            chunks_path=chunks_rel,
            manifest_path=_rel_media_path(manifest_path, self.media_root),
            run_summary_path=_rel_media_path(summary_path, self.media_root),
            failures=failures,
        )

        summary_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
        shutil.copyfile(chunks_path, self.chunks_root / "latest.jsonl")
        shutil.copyfile(manifest_path, self.manifests_root / "latest.jsonl")
        shutil.copyfile(summary_path, self.runs_root / "latest.json")
        return summary

    def _load_processed_source_keys(self) -> set[str]:
        latest_manifest = self.manifests_root / "latest.jsonl"
        if not latest_manifest.exists():
            return set()

        processed: set[str] = set()
        for raw_line in latest_manifest.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if row.get("status") != "success":
                continue
            source_key = str(row.get("source_key") or "").strip()
            if source_key:
                processed.add(source_key)
        return processed

    def _chunk_one_record(self, record: dict[str, Any], source_key: str) -> dict[str, Any]:
        text_rel_path = str(record.get("text_path") or "").strip()
        source_abs = self.media_root / text_rel_path
        if not source_abs.exists():
            return {
                "status": "failed",
                "error": f"text file missing: {source_abs}",
                "chunk_count": 0,
                "text_chars": 0,
                "chunk_rows": [],
            }

        try:
            text = source_abs.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {
                "status": "failed",
                "error": f"read failure: {exc}",
                "chunk_count": 0,
                "text_chars": 0,
                "chunk_rows": [],
            }

        text_chars = len(text)
        chunks = [chunk for chunk in _chunk_text(text, self.chunk_chars) if len(chunk.strip()) >= self.min_chunk_chars]

        source_url = record.get("url") or ""
        title = record.get("title") or ""
        source_sha = str(record.get("sha256") or "")
        chunk_rows: list[dict[str, Any]] = []
        for idx, chunk_text in enumerate(chunks, start=1):
            chunk_rows.append(
                {
                    "chunk_id": f"{source_key}-{idx}",
                    "source_key": source_key,
                    "source_url": source_url,
                    "source_sha256": source_sha,
                    "title": title,
                    "source_text_path": text_rel_path,
                    "chunk_index": idx,
                    "char_count": len(chunk_text),
                    "text": chunk_text,
                }
            )

        return {
            "status": "success",
            "error": "",
            "chunk_count": len(chunk_rows),
            "text_chars": text_chars,
            "chunk_rows": chunk_rows,
        }
