from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import shutil
import threading
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib import robotparser
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from django.db import OperationalError, ProgrammingError
from django.db.models import Count, Q, Sum


LOGGER = logging.getLogger(__name__)

DEFAULT_START_URL = "https://www.sedro-woolley.gov/"
DEFAULT_USER_AGENT = "OpenSkagitSedroCrawler/1.0 (+https://openskagit.com)"

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_source",
    "utm_term",
}

MEETING_MINUTES_KEYWORDS = (
    "meeting minute",
    "meeting minutes",
    "city council meeting",
    "planning commission meeting",
    "work session",
    "minutes",
)

AGENDA_KEYWORDS = (
    "agenda",
    "agenda packet",
    "meeting packet",
)

BUDGET_FINANCE_KEYWORDS = (
    "budget",
    "financial",
    "finance",
    "annual comprehensive financial report",
    "acfr",
    "audit report",
    "capital improvement plan",
)

ORDINANCE_KEYWORDS = (
    "ordinance",
    "/ord/",
)

RESOLUTION_KEYWORDS = (
    "resolution",
    "res.",
)

REPORT_KEYWORDS = (
    "report",
    "study",
)

PRIORITY_KEYWORDS = (
    "meeting",
    "minutes",
    "agenda",
    "budget",
    "finance",
    "financial",
)

BINARY_EXTENSIONS = {
    ".7z",
    ".asc",
    ".bmp",
    ".csv",
    ".doc",
    ".docm",
    ".docx",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".json",
    ".kml",
    ".kmz",
    ".mov",
    ".mp3",
    ".mp4",
    ".msg",
    ".odt",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rtf",
    ".svg",
    ".tar",
    ".tif",
    ".tiff",
    ".txt",
    ".wav",
    ".webm",
    ".xls",
    ".xlsm",
    ".xlsx",
    ".xml",
    ".zip",
}

CONTENT_TYPE_EXTENSIONS = {
    "application/json": ".json",
    "application/msword": ".doc",
    "application/octet-stream": ".bin",
    "application/pdf": ".pdf",
    "application/rtf": ".rtf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/xml": ".xml",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "text/xml": ".xml",
}

HTML_CONTENT_MARKERS = (
    "text/html",
    "application/xhtml+xml",
)

SITEMAP_CONTENT_MARKERS = (
    "application/xml",
    "text/xml",
    "application/x-gzip",
)

SITEMAP_CANDIDATES = ("/sitemap.xml", "/sitemap_index.xml")

SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "ftp"}

URL_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class CrawlRecord:
    record: dict[str, Any]
    discovered_links: list[str]


@dataclass
class CrawlSummary:
    run_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    urls_processed: int
    urls_seen: int
    records_written: int
    html_pages: int
    files: int
    failure_count: int
    by_resource_type: dict[str, int]
    by_extension: dict[str, int]
    tag_counts: dict[str, int]
    failures: list[dict[str, Any]]
    manifest_path: str
    run_summary_path: str
    start_url: str
    allowed_domains: list[str]
    max_depth: int
    max_pages: int
    resumed: bool
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "urls_processed": self.urls_processed,
            "urls_seen": self.urls_seen,
            "records_written": self.records_written,
            "html_pages": self.html_pages,
            "files": self.files,
            "failure_count": self.failure_count,
            "by_resource_type": self.by_resource_type,
            "by_extension": self.by_extension,
            "tag_counts": self.tag_counts,
            "failures": self.failures,
            "manifest_path": self.manifest_path,
            "run_summary_path": self.run_summary_path,
            "start_url": self.start_url,
            "allowed_domains": self.allowed_domains,
            "max_depth": self.max_depth,
            "max_pages": self.max_pages,
            "resumed": self.resumed,
            "dry_run": self.dry_run,
        }


def normalize_url(url: str) -> str:
    """Normalize URLs so duplicates collapse to a single key."""

    if not url:
        return ""

    trimmed = url.strip()
    if not trimmed:
        return ""

    clean_url, _fragment = urldefrag(trimmed)
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() not in {"http", "https"}:
        return ""

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    filtered_query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key.startswith("utm_"):
            continue
        if lower_key in TRACKING_QUERY_KEYS:
            continue
        filtered_query.append((key, value))

    query = urlencode(sorted(filtered_query), doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def infer_document_tags(url: str, title: str = "", text: str = "") -> set[str]:
    haystack = " ".join([url, title, text]).lower()
    tags: set[str] = set()

    if any(keyword in haystack for keyword in MEETING_MINUTES_KEYWORDS):
        tags.add("meeting_minutes")

    if any(keyword in haystack for keyword in AGENDA_KEYWORDS):
        tags.add("agenda_packet")

    if any(keyword in haystack for keyword in BUDGET_FINANCE_KEYWORDS):
        tags.add("budget_finance")

    if any(keyword in haystack for keyword in ORDINANCE_KEYWORDS):
        tags.add("ordinance")

    if any(keyword in haystack for keyword in RESOLUTION_KEYWORDS):
        tags.add("resolution")

    if any(keyword in haystack for keyword in REPORT_KEYWORDS):
        tags.add("report")

    if not tags:
        tags.add("general")

    return tags


def should_prioritize_url(url: str) -> bool:
    candidate = url.lower()
    return any(keyword in candidate for keyword in PRIORITY_KEYWORDS)


def infer_extension(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix:
        return suffix

    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_EXTENSIONS.get(normalized_content_type, ".bin")


def classify_resource_type(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return "binary_file"

    normalized_content_type = (content_type or "").lower()
    if any(marker in normalized_content_type for marker in HTML_CONTENT_MARKERS):
        return "html_page"

    if normalized_content_type.startswith("text/") and "xml" not in normalized_content_type:
        return "html_page"

    return "binary_file"


def rel_media_path(path: Path, media_root: Path) -> str:
    return str(path.relative_to(media_root)).replace("\\", "/")


def _sanitize_name(name: str) -> str:
    cleaned = URL_SAFE_CHARS.sub("_", name.strip())
    cleaned = cleaned.strip("._")
    return cleaned[:120] if cleaned else "item"


def _build_storage_path(root: Path, category: str, url: str, ext: str, *, force_extension: bool = False) -> Path:
    parsed = urlparse(url)
    host_part = _sanitize_name(parsed.netloc or "unknown-host")
    source_name = Path(parsed.path).name
    if not source_name:
        source_name = "index"
    source_name = _sanitize_name(source_name)

    suffix = Path(source_name).suffix.lower()
    if force_extension:
        stem = Path(source_name).stem
        final_name = f"{stem or source_name}{ext}"
    elif suffix:
        final_name = source_name
    else:
        final_name = f"{source_name}{ext}"

    url_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    final_name = f"{url_digest}_{final_name}"

    return root / category / host_part / final_name


def _extract_html_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()

    first_heading = soup.find(["h1", "h2"])
    if first_heading:
        return first_heading.get_text(" ", strip=True)

    return ""


def _body_text_to_markdown(title: str, body_text: str) -> str:
    lines: list[str] = []
    heading = (title or "").strip()
    if heading:
        lines.append(f"# {heading}")
        lines.append("")

    normalized = (body_text or "").strip()
    if normalized:
        lines.append(normalized)
    else:
        lines.append("_No body text extracted._")

    return "\n".join(lines).strip() + "\n"


def _looks_like_chrome_container(node: Any) -> bool:
    if not hasattr(node, "get"):
        return False
    if not getattr(node, "attrs", None):
        return False

    try:
        css_classes = " ".join(node.get("class") or [])
        element_id = node.get("id") or ""
    except Exception:
        return False
    haystack = f"{css_classes} {element_id}".lower()
    if not haystack.strip():
        return False

    hints = (
        "nav",
        "menu",
        "header",
        "footer",
        "breadcrumb",
        "social",
        "translate",
        "skip",
        "toolbar",
    )
    return any(hint in haystack for hint in hints)


def _extract_text_and_links(base_url: str, html: str) -> tuple[str, str, str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")

    for node in soup(["script", "style", "noscript"]):
        node.decompose()

    title = _extract_html_title(soup)

    resolution_base = base_url
    base_tag = soup.find("base", href=True)
    if base_tag and base_tag.get("href"):
        normalized_base = _normalize_candidate_link(base_url, str(base_tag.get("href")))
        if normalized_base:
            resolution_base = normalized_base

    body = soup.body if soup.body else soup
    for node in body(["code", "pre", "svg", "canvas", "nav", "header", "footer", "aside", "form"]):
        node.decompose()

    for node in list(body.find_all(True)):
        if _looks_like_chrome_container(node):
            node.decompose()

    for node in body(["button", "select", "option", "label"]):
        node.decompose()

    text_lines = [line.strip() for line in body.get_text("\n").splitlines() if line.strip()]
    text = "\n".join(text_lines)
    markdown_text = _body_text_to_markdown(title, text)

    links: set[str] = set()

    for tag, attr in (("a", "href"), ("iframe", "src"), ("embed", "src"), ("object", "data"), ("link", "href")):
        for node in soup.find_all(tag):
            raw_target = node.get(attr)
            if not raw_target:
                continue
            normalized = _normalize_candidate_link(resolution_base, raw_target)
            if normalized:
                links.add(normalized)

    for match in re.findall(r"https?://[^\s\"'<>]+", html, flags=re.IGNORECASE):
        normalized = normalize_url(match)
        if normalized:
            links.add(normalized)

    return title, text, markdown_text, sorted(links)


def _normalize_candidate_link(base_url: str, candidate: str) -> str:
    raw_value = (candidate or "").strip()
    if not raw_value:
        return ""

    if raw_value.startswith("#!/"):
        raw_value = raw_value[2:]

    if raw_value.startswith("#"):
        return ""

    parsed = urlparse(raw_value)
    if parsed.scheme and parsed.scheme.lower() in SKIP_SCHEMES:
        return ""

    joined = urljoin(base_url, raw_value)
    return normalize_url(joined)


def _parse_sitemap_urls(payload: str) -> list[str]:
    soup = BeautifulSoup(payload, "xml")
    locations = []
    for loc_tag in soup.find_all("loc"):
        value = (loc_tag.get_text() or "").strip()
        normalized = normalize_url(value)
        if normalized:
            locations.append(normalized)
    return locations


def _looks_like_sitemap_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return "sitemap" in path or path.endswith(".xml")


def load_sw_dashboard_context(
    *,
    media_root: Path,
    media_url: str,
    tag_filter: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 500,
) -> dict[str, Any]:
    db_payload = _load_dashboard_from_db(
        media_root=media_root,
        media_url=media_url,
        tag_filter=tag_filter,
        query=query,
        limit=limit,
    )
    if db_payload:
        return db_payload

    # File fallback if database tables are unavailable.
    root = media_root / "sedro_woolley"
    summary_path = root / "runs" / "latest.json"
    manifest_path = root / "manifests" / "latest.jsonl"

    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("Could not decode Sedro-Woolley latest summary at %s", summary_path)

    records: list[dict[str, Any]] = []
    if manifest_path.exists():
        for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                records.append(json.loads(raw_line))
            except json.JSONDecodeError:
                LOGGER.warning("Skipping malformed record in %s", manifest_path)
    legal_context = _load_legal_code_context(query=query, limit=limit)
    pipeline_summary = _load_pipeline_summaries(media_root)

    if isinstance(summary, dict):
        summary.setdefault("scope", "latest_run_files")
        manifest_rel = summary.get("manifest_path")
        run_summary_rel = summary.get("run_summary_path")
        if manifest_rel:
            summary["manifest_absolute_path"] = str(media_root / manifest_rel)
        if run_summary_rel:
            summary["run_summary_absolute_path"] = str(media_root / run_summary_rel)

    records.sort(key=lambda row: row.get("fetched_at", ""), reverse=True)

    tag_filter_value = (tag_filter or "").strip().lower()
    query_value = (query or "").strip().lower()

    filtered_records: list[dict[str, Any]] = []
    for row in records:
        tags = [tag.lower() for tag in row.get("tags") or []]

        if tag_filter_value and tag_filter_value not in tags:
            continue

        if query_value:
            search_blob = " ".join(
                [
                    row.get("url") or "",
                    row.get("title") or "",
                    " ".join(row.get("tags") or []),
                ]
            ).lower()
            if query_value not in search_blob:
                continue

        enriched = dict(row)
        enriched.setdefault("download_url", "")
        enriched.setdefault("text_download_url", "")
        enriched.setdefault("raw_html_download_url", "")
        media_path = enriched.get("media_path")
        text_path = enriched.get("text_path")
        raw_html_path = enriched.get("raw_html_path")

        if media_path:
            enriched["download_url"] = _join_media_url(media_url, media_path)
        if text_path:
            enriched["text_download_url"] = _join_media_url(media_url, text_path)
        if raw_html_path:
            enriched["raw_html_download_url"] = _join_media_url(media_url, raw_html_path)

        filtered_records.append(enriched)

        if len(filtered_records) >= limit:
            break

    available_tags = sorted({tag for row in records for tag in row.get("tags") or []})
    latest_run = {
        "run_id": summary.get("run_id") if isinstance(summary, dict) else "",
        "started_at": summary.get("started_at") if isinstance(summary, dict) else "",
        "finished_at": summary.get("finished_at") if isinstance(summary, dict) else "",
        "duration_seconds": summary.get("duration_seconds") if isinstance(summary, dict) else 0,
        "failure_count": summary.get("failure_count") if isinstance(summary, dict) else 0,
        "manifest_path": summary.get("manifest_path") if isinstance(summary, dict) else "",
        "run_summary_path": summary.get("run_summary_path") if isinstance(summary, dict) else "",
    }

    return {
        "summary": summary,
        "latest_run": latest_run,
        "records": filtered_records,
        "available_tags": available_tags,
        "category_stats": {
            "by_resource_type": summary.get("by_resource_type") if isinstance(summary, dict) else {},
            "by_extension": summary.get("by_extension") if isinstance(summary, dict) else {},
            "tag_counts": summary.get("tag_counts") if isinstance(summary, dict) else {},
        },
        "pipeline_summary": pipeline_summary,
        "legal_summary": legal_context.get("summary") or {},
        "legal_records": legal_context.get("records") or [],
        "legal_jurisdictions": legal_context.get("jurisdictions") or [],
        "has_data": bool(summary or records or legal_context.get("has_data")),
    }


def _join_media_url(base: str, rel_path: str) -> str:
    base_url = base if base.endswith("/") else f"{base}/"
    return f"{base_url}{rel_path.lstrip('/')}"


def _load_dashboard_from_db(
    *,
    media_root: Path,
    media_url: str,
    tag_filter: Optional[str],
    query: Optional[str],
    limit: int,
) -> dict[str, Any]:
    try:
        from openskagit.models import SedroWoolleyCrawlDocument, SedroWoolleyCrawlRun
    except Exception:
        return {}

    try:
        run_qs = SedroWoolleyCrawlRun.objects.all()
        latest_run = run_qs.order_by("-started_at").first()
    except (OperationalError, ProgrammingError):
        return {}

    legal_context = _load_legal_code_context(query=query, limit=limit)

    try:
        doc_qs = SedroWoolleyCrawlDocument.objects.order_by("-fetched_at")
    except (OperationalError, ProgrammingError):
        doc_qs = SedroWoolleyCrawlDocument.objects.none()

    doc_values = doc_qs.values(
        "run__run_id",
        "url",
        "source_url",
        "depth",
        "resource_type",
        "title",
        "tags",
        "status_code",
        "content_type",
        "extension",
        "size_bytes",
        "sha256",
        "fetched_at",
        "media_path",
        "raw_html_path",
        "text_path",
    )

    tag_filter_value = (tag_filter or "").strip().lower()
    query_value = (query or "").strip().lower()

    resource_type_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    available_tags: set[str] = set()
    filtered_records: list[dict[str, Any]] = []

    for row in doc_values:
        resource_type = str(row.get("resource_type") or "unknown")
        extension = str(row.get("extension") or "").lower()
        tags = [str(tag) for tag in row.get("tags") or []]
        tags_lower = [tag.lower() for tag in tags]

        resource_type_counts[resource_type] += 1
        if extension:
            extension_counts[extension] += 1
        for tag in tags:
            available_tags.add(tag)
            tag_counts[tag] += 1

        if tag_filter_value and tag_filter_value not in tags_lower:
            continue

        if query_value:
            search_blob = " ".join(
                [
                    str(row.get("url") or ""),
                    str(row.get("title") or ""),
                    resource_type,
                    extension,
                    " ".join(tags),
                ]
            ).lower()
            if query_value not in search_blob:
                continue

        if len(filtered_records) >= limit:
            continue

        fetched_at = row.get("fetched_at")
        media_path = str(row.get("media_path") or "")
        text_path = str(row.get("text_path") or "")
        raw_html_path = str(row.get("raw_html_path") or "")

        enriched = {
            "run_id": row.get("run__run_id") or "",
            "url": row.get("url") or "",
            "source_url": row.get("source_url"),
            "depth": row.get("depth") or 0,
            "resource_type": resource_type,
            "title": row.get("title") or "",
            "tags": tags,
            "status_code": row.get("status_code"),
            "content_type": row.get("content_type") or "",
            "extension": extension,
            "size_bytes": row.get("size_bytes") or 0,
            "sha256": row.get("sha256") or "",
            "fetched_at": fetched_at.isoformat() if getattr(fetched_at, "isoformat", None) else "",
            "media_path": media_path,
            "raw_html_path": raw_html_path,
            "text_path": text_path,
            "download_url": "",
            "text_download_url": "",
            "raw_html_download_url": "",
        }
        if media_path:
            enriched["download_url"] = _join_media_url(media_url, media_path)
        if text_path:
            enriched["text_download_url"] = _join_media_url(media_url, text_path)
        if raw_html_path:
            enriched["raw_html_download_url"] = _join_media_url(media_url, raw_html_path)

        filtered_records.append(enriched)

    run_aggregates = run_qs.aggregate(
        urls_processed_total=Sum("urls_processed"),
        urls_seen_total=Sum("urls_seen"),
        failures_total=Sum("failure_count"),
    )
    total_docs = sum(resource_type_counts.values())
    html_pages = resource_type_counts.get("html_page", 0)
    files = max(total_docs - html_pages, 0)
    latest_summary = {
        "run_id": latest_run.run_id if latest_run else "",
        "started_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else "",
        "finished_at": latest_run.finished_at.isoformat() if latest_run and latest_run.finished_at else "",
        "duration_seconds": latest_run.duration_seconds if latest_run else None,
        "failure_count": latest_run.failure_count if latest_run else 0,
        "manifest_path": latest_run.manifest_path if latest_run else "",
        "run_summary_path": latest_run.run_summary_path if latest_run else "",
    }
    summary = {
        "scope": "all_runs",
        "total_runs": run_qs.count(),
        "urls_processed": run_aggregates.get("urls_processed_total") or 0,
        "urls_seen": run_aggregates.get("urls_seen_total") or 0,
        "records_written": total_docs,
        "html_pages": html_pages,
        "files": files,
        "failure_count": run_aggregates.get("failures_total") or 0,
        "started_at": latest_summary["started_at"],
        "finished_at": latest_summary["finished_at"],
        "duration_seconds": latest_summary["duration_seconds"] or 0,
        "manifest_path": latest_summary["manifest_path"],
        "run_summary_path": latest_summary["run_summary_path"],
        "latest_run_id": latest_summary["run_id"],
    }
    manifest_rel = summary.get("manifest_path")
    run_summary_rel = summary.get("run_summary_path")
    if manifest_rel:
        summary["manifest_absolute_path"] = str(media_root / manifest_rel)
    if run_summary_rel:
        summary["run_summary_absolute_path"] = str(media_root / run_summary_rel)

    pipeline_summary = _load_pipeline_summaries(media_root)

    has_crawl_data = bool(total_docs or run_qs.exists())
    has_legal_data = bool(legal_context.get("has_data"))

    return {
        "summary": summary,
        "latest_run": latest_summary,
        "records": filtered_records,
        "available_tags": sorted(available_tags, key=lambda value: value.lower()),
        "category_stats": {
            "by_resource_type": dict(resource_type_counts),
            "by_extension": dict(extension_counts.most_common(15)),
            "tag_counts": dict(tag_counts.most_common(20)),
        },
        "pipeline_summary": pipeline_summary,
        "legal_summary": legal_context.get("summary") or {},
        "legal_records": legal_context.get("records") or [],
        "legal_jurisdictions": legal_context.get("jurisdictions") or [],
        "has_data": bool(has_crawl_data or has_legal_data),
    }


def _load_pipeline_summaries(media_root: Path) -> dict[str, dict[str, Any]]:
    root = media_root / "sedro_woolley"
    payload: dict[str, dict[str, Any]] = {
        "pdf_ingest": {"run_id": "", "success_count": 0, "failure_count": 0},
        "html_ingest": {"run_id": "", "success_count": 0, "failure_count": 0},
    }

    for key, rel in (
        ("pdf_ingest", root / "pdf_ingest" / "runs" / "latest.json"),
        ("html_ingest", root / "html_ingest" / "runs" / "latest.json"),
    ):
        if not rel.exists():
            continue
        try:
            summary = json.loads(rel.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        summary = dict(summary)
        summary.setdefault("run_id", "")
        summary.setdefault("success_count", summary.get("processed_count") or summary.get("records_found") or 0)
        summary.setdefault("failure_count", summary.get("failed_count") or 0)
        summary["summary_absolute_path"] = str(rel)
        chunks_rel = summary.get("chunks_path")
        if chunks_rel:
            summary["chunks_absolute_path"] = str(media_root / chunks_rel)
        payload[key] = summary

    return payload


def _load_legal_code_context(*, query: Optional[str], limit: int) -> dict[str, Any]:
    try:
        from legal_code.models import Jurisdiction, LawChapter, LawDocument, LawSection, LawSectionChunk
    except Exception:
        return {"summary": {}, "records": [], "jurisdictions": [], "has_data": False}

    query_value = (query or "").strip()
    try:
        sedro_jur_qs = Jurisdiction.objects.filter(
            Q(name__icontains="sedro")
            | Q(name__icontains="woolley")
            | Q(aliases__alias__icontains="sedro")
            | Q(aliases__alias__icontains="woolley")
        ).distinct().order_by("name")
        jurisdictions = list(sedro_jur_qs.values_list("name", flat=True))
    except (OperationalError, ProgrammingError):
        return {"summary": {}, "records": [], "jurisdictions": [], "has_data": False}

    if not jurisdictions:
        return {"summary": {}, "records": [], "jurisdictions": [], "has_data": False}

    try:
        docs_count = LawDocument.objects.filter(jurisdiction__in=sedro_jur_qs).count()
        chapters_count = LawChapter.objects.filter(document__jurisdiction__in=sedro_jur_qs).count()
        sections_all_qs = LawSection.objects.filter(chapter__document__jurisdiction__in=sedro_jur_qs)
        sections_qs = sections_all_qs
        chunks_count = LawSectionChunk.objects.filter(jurisdiction__in=sedro_jur_qs).count()
    except (OperationalError, ProgrammingError):
        return {"summary": {}, "records": [], "jurisdictions": jurisdictions, "has_data": False}

    if query_value:
        sections_qs = sections_qs.filter(
            Q(section_id__icontains=query_value)
            | Q(heading__icontains=query_value)
            | Q(content__icontains=query_value)
            | Q(source_url__icontains=query_value)
        )

    section_rows = (
        sections_qs.select_related("chapter__document__jurisdiction")
        .annotate(chunk_count=Count("chunks"))
        .order_by("-scraped_at")[: max(1, min(limit, 200))]
    )
    records = []
    for row in section_rows:
        records.append(
            {
                "jurisdiction": row.chapter.document.jurisdiction.name if row.chapter and row.chapter.document else "",
                "section_id": row.section_id,
                "heading": row.heading,
                "source_url": row.source_url,
                "scraped_at": row.scraped_at.isoformat() if row.scraped_at else "",
                "chunk_count": row.chunk_count,
            }
        )

    summary = {
        "jurisdiction_count": len(jurisdictions),
        "document_count": docs_count,
        "chapter_count": chapters_count,
        "section_count": sections_all_qs.count(),
        "chunk_count": chunks_count,
        "result_count": len(records),
    }

    return {
        "summary": summary,
        "records": records,
        "jurisdictions": jurisdictions,
        "has_data": bool(summary["document_count"] or summary["section_count"]),
    }


def _coerce_iso_datetime(value: str) -> dt.datetime:
    normalized = (value or "").strip()
    if not normalized:
        return dt.datetime.now(dt.timezone.utc)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


class SedroWoolleyCrawler:
    def __init__(
        self,
        *,
        start_url: str,
        media_root: Path,
        allowed_domains: Iterable[str],
        max_pages: int,
        max_depth: int,
        delay_ms: int,
        timeout_seconds: int,
        resume: bool,
        dry_run: bool,
        workers: int,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.start_url = normalize_url(start_url)
        self.media_root = media_root
        self.root = media_root / "sedro_woolley"

        if not self.start_url:
            raise ValueError("Invalid start URL")

        start_domain = (urlparse(self.start_url).hostname or "").lower()
        normalized_domains = {start_domain}
        normalized_domains.update(domain.lower().strip() for domain in allowed_domains if domain)
        self.allowed_domains = {domain for domain in normalized_domains if domain}

        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay_seconds = max(delay_ms, 0) / 1000.0
        self.timeout_seconds = timeout_seconds
        self.resume = resume
        self.dry_run = dry_run
        self.workers = max(1, workers)
        self.user_agent = user_agent

        self.session = self._build_session()
        self._thread_local = threading.local()

        self.robot_parsers: dict[str, Optional[robotparser.RobotFileParser]] = {}
        self.queued: deque[tuple[str, int, Optional[str]]] = deque()
        self.queued_set: set[str] = set()
        self.seen_urls: set[str] = set()
        self.pdf_hash_to_media_path: dict[str, str] = {}
        self.pdf_hash_lock = threading.Lock()

        self.processed_count = 0
        self.records_written = 0
        self.type_counts: Counter[str] = Counter()
        self.extension_counts: Counter[str] = Counter()
        self.tag_counts: Counter[str] = Counter()
        self.failures: list[dict[str, Any]] = []

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        return session

    def _get_worker_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._build_session()
            self._thread_local.session = session
        return session

    def crawl(self) -> CrawlSummary:
        start_clock = time.monotonic()
        started_at = dt.datetime.now(dt.timezone.utc)
        run_id = started_at.strftime("%Y%m%dT%H%M%SZ")

        manifests_dir = self.root / "manifests"
        runs_dir = self.root / "runs"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        runs_dir.mkdir(parents=True, exist_ok=True)

        if not self.dry_run:
            (self.root / "text").mkdir(parents=True, exist_ok=True)
            (self.root / "files").mkdir(parents=True, exist_ok=True)

        run_manifest_path = manifests_dir / f"{run_id}.jsonl"
        run_summary_path = runs_dir / f"{run_id}.json"

        self._load_existing_pdf_hash_index()

        resumed = False
        if self.resume:
            resumed = self._load_resume_state()

        run_row = self._create_run_record(run_id=run_id, started_at=started_at)

        self._enqueue(self.start_url, depth=0, source_url=None)
        self._seed_sitemaps()

        with run_manifest_path.open("w", encoding="utf-8") as manifest_handle:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                in_flight: dict[Any, tuple[str, int, Optional[str]]] = {}

                while True:
                    while len(in_flight) < self.workers and self.processed_count < self.max_pages:
                        task = self._next_crawl_task()
                        if task is None:
                            break
                        url, depth, source_url = task
                        future = executor.submit(
                            self._fetch_and_build_record,
                            url=url,
                            depth=depth,
                            source_url=source_url,
                        )
                        in_flight[future] = task

                    if not in_flight:
                        break

                    done, _pending = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
                    for finished in done:
                        url, depth, source_url = in_flight.pop(finished)

                        try:
                            result = finished.result()
                        except Exception as exc:  # pragma: no cover - defensive capture in worker
                            self._record_failure(
                                url=url,
                                source_url=source_url,
                                depth=depth,
                                error=f"worker failure: {exc}",
                            )
                            continue

                        if not result.get("ok"):
                            self._record_failure(
                                url=result.get("url") or url,
                                source_url=result.get("source_url") or source_url,
                                depth=result.get("depth") or depth,
                                error=str(result.get("error") or "unknown error"),
                                status_code=result.get("status_code"),
                            )
                            continue

                        final_url = result["final_url"]
                        crawl_record: CrawlRecord = result["crawl_record"]

                        if final_url != url and final_url not in self.seen_urls:
                            self.seen_urls.add(final_url)

                        manifest_handle.write(json.dumps(crawl_record.record, ensure_ascii=True) + "\n")
                        self.records_written += 1
                        self.type_counts[crawl_record.record["resource_type"]] += 1
                        self.extension_counts[crawl_record.record["extension"]] += 1
                        for tag in crawl_record.record.get("tags", []):
                            self.tag_counts[tag] += 1

                        self._save_document_record(run_row=run_row, record=crawl_record.record)

                        for discovered in crawl_record.discovered_links:
                            if depth + 1 > self.max_depth:
                                continue
                            self._enqueue(discovered, depth=depth + 1, source_url=final_url)

        finished_at = dt.datetime.now(dt.timezone.utc)
        duration = round(time.monotonic() - start_clock, 2)

        summary = CrawlSummary(
            run_id=run_id,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=duration,
            urls_processed=self.processed_count,
            urls_seen=len(self.seen_urls),
            records_written=self.records_written,
            html_pages=self.type_counts.get("html_page", 0),
            files=self.type_counts.get("binary_file", 0),
            failure_count=len(self.failures),
            by_resource_type=dict(self.type_counts),
            by_extension=dict(self.extension_counts),
            tag_counts=dict(self.tag_counts),
            failures=self.failures,
            manifest_path=rel_media_path(run_manifest_path, self.media_root),
            run_summary_path=rel_media_path(run_summary_path, self.media_root),
            start_url=self.start_url,
            allowed_domains=sorted(self.allowed_domains),
            max_depth=self.max_depth,
            max_pages=self.max_pages,
            resumed=resumed,
            dry_run=self.dry_run,
        )

        run_summary_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")

        latest_manifest = manifests_dir / "latest.jsonl"
        latest_summary = runs_dir / "latest.json"
        shutil.copyfile(run_manifest_path, latest_manifest)
        shutil.copyfile(run_summary_path, latest_summary)

        self._finalize_run_record(run_row=run_row, summary=summary)

        return summary

    def _next_crawl_task(self) -> Optional[tuple[str, int, Optional[str]]]:
        while self.queued and self.processed_count < self.max_pages:
            url, depth, source_url = self.queued.popleft()
            self.queued_set.discard(url)

            if url in self.seen_urls:
                continue
            if depth > self.max_depth:
                continue
            if not self._is_allowed_domain(url):
                continue
            if not self._can_fetch(url):
                LOGGER.info("robots.txt disallow: %s", url)
                continue

            self.seen_urls.add(url)
            self.processed_count += 1

            if self.delay_seconds:
                time.sleep(self.delay_seconds)

            return url, depth, source_url

        return None

    def _fetch_and_build_record(self, *, url: str, depth: int, source_url: Optional[str]) -> dict[str, Any]:
        session = self._get_worker_session()
        try:
            response = session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
        except requests.RequestException as exc:
            return {
                "ok": False,
                "url": url,
                "source_url": source_url,
                "depth": depth,
                "status_code": None,
                "error": str(exc),
            }

        final_url = normalize_url(response.url) or url
        if response.status_code >= 400:
            return {
                "ok": False,
                "url": final_url,
                "source_url": source_url,
                "depth": depth,
                "status_code": response.status_code,
                "error": f"HTTP {response.status_code}",
            }

        content_type = response.headers.get("Content-Type", "")
        resource_type = classify_resource_type(final_url, content_type)

        try:
            crawl_record = self._build_record(
                final_url=final_url,
                source_url=source_url,
                depth=depth,
                response=response,
                resource_type=resource_type,
            )
        except Exception as exc:  # pragma: no cover - defensive capture in long-running crawler
            return {
                "ok": False,
                "url": final_url,
                "source_url": source_url,
                "depth": depth,
                "status_code": response.status_code,
                "error": f"record build failure: {exc}",
            }

        return {
            "ok": True,
            "url": url,
            "source_url": source_url,
            "depth": depth,
            "final_url": final_url,
            "crawl_record": crawl_record,
        }

    def _load_resume_state(self) -> bool:
        latest_manifest = self.root / "manifests" / "latest.jsonl"
        if not latest_manifest.exists():
            return False

        loaded_any = False
        for raw_line in latest_manifest.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            normalized = normalize_url(entry.get("url", ""))
            if normalized:
                self.seen_urls.add(normalized)
                loaded_any = True

        return loaded_any

    def _load_existing_pdf_hash_index(self) -> None:
        latest_manifest = self.root / "manifests" / "latest.jsonl"
        if not latest_manifest.exists():
            return

        for raw_line in latest_manifest.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            extension = str(row.get("extension") or "").lower()
            content_type = str(row.get("content_type") or "").lower()
            if extension != ".pdf" and "application/pdf" not in content_type:
                continue

            digest = str(row.get("sha256") or "").strip().lower()
            media_path = str(row.get("media_path") or "").strip()
            if not digest or not media_path:
                continue

            self.pdf_hash_to_media_path.setdefault(digest, media_path)

    def _seed_sitemaps(self) -> None:
        for domain in sorted(self.allowed_domains):
            base_url = f"https://{domain}"
            robots_url = f"{base_url}/robots.txt"
            discovered_sitemaps: set[str] = set()

            try:
                response = self.session.get(robots_url, timeout=self.timeout_seconds)
                if response.status_code == 200:
                    for line in response.text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            candidate = line.split(":", 1)[1].strip()
                            normalized = normalize_url(candidate)
                            if normalized:
                                discovered_sitemaps.add(normalized)
            except requests.RequestException:
                LOGGER.debug("robots.txt unavailable for %s", domain)

            for candidate in SITEMAP_CANDIDATES:
                normalized = normalize_url(f"{base_url}{candidate}")
                if normalized:
                    discovered_sitemaps.add(normalized)

            pending = deque(sorted(discovered_sitemaps))
            visited_sitemaps: set[str] = set()
            while pending:
                sitemap_url = pending.popleft()
                if sitemap_url in visited_sitemaps:
                    continue
                visited_sitemaps.add(sitemap_url)
                try:
                    response = self.session.get(sitemap_url, timeout=self.timeout_seconds)
                except requests.RequestException:
                    continue

                if response.status_code != 200:
                    continue

                content_type = response.headers.get("Content-Type", "").lower()
                if not any(marker in content_type for marker in SITEMAP_CONTENT_MARKERS):
                    # Some sites send text/plain for XML; still try parse.
                    pass

                for discovered_url in _parse_sitemap_urls(response.text):
                    if _looks_like_sitemap_url(discovered_url):
                        if discovered_url not in visited_sitemaps:
                            pending.append(discovered_url)
                        continue

                    if self._is_allowed_domain(discovered_url):
                        self._enqueue(discovered_url, depth=1, source_url=sitemap_url)

    def _enqueue(self, url: str, depth: int, source_url: Optional[str]) -> None:
        normalized = normalize_url(url)
        if not normalized:
            return
        if normalized in self.seen_urls or normalized in self.queued_set:
            return
        if not self._is_allowed_domain(normalized):
            return

        if should_prioritize_url(normalized):
            self.queued.appendleft((normalized, depth, source_url))
        else:
            self.queued.append((normalized, depth, source_url))
        self.queued_set.add(normalized)

    def _is_allowed_domain(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False

        for allowed in self.allowed_domains:
            if host == allowed or host.endswith(f".{allowed}"):
                return True

        return False

    def _can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False

        parser = self.robot_parsers.get(host)
        if parser is None and host not in self.robot_parsers:
            robots_url = f"{parsed.scheme}://{host}/robots.txt"
            parser = robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
            except Exception:
                parser = None
            self.robot_parsers[host] = parser

        parser = self.robot_parsers.get(host)
        if parser is None:
            return True

        try:
            return parser.can_fetch(self.session.headers.get("User-Agent", DEFAULT_USER_AGENT), url)
        except Exception:
            return True

    def _build_record(
        self,
        *,
        final_url: str,
        source_url: Optional[str],
        depth: int,
        response: requests.Response,
        resource_type: str,
    ) -> CrawlRecord:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        extension = infer_extension(final_url, content_type)

        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()

        if resource_type == "html_page":
            payload = response.text
            payload_bytes = payload.encode("utf-8", errors="ignore")
            digest = hashlib.sha256(payload_bytes).hexdigest()

            title, text, markdown_text, links = _extract_text_and_links(final_url, payload)
            tags = sorted(infer_document_tags(final_url, title=title, text=text[:4000]))

            text_path = _build_storage_path(self.root, "text", final_url, ".md", force_extension=True)

            if not self.dry_run:
                text_path.parent.mkdir(parents=True, exist_ok=True)
                text_path.write_text(markdown_text, encoding="utf-8", errors="ignore")

            record = {
                "url": final_url,
                "source_url": source_url,
                "depth": depth,
                "resource_type": resource_type,
                "title": title,
                "tags": tags,
                "status_code": response.status_code,
                "content_type": content_type,
                "extension": ".html",
                "size_bytes": len(payload_bytes),
                "sha256": digest,
                "fetched_at": fetched_at,
                "media_path": rel_media_path(text_path, self.media_root),
                "raw_html_path": "",
                "text_path": rel_media_path(text_path, self.media_root),
                "markdown_path": rel_media_path(text_path, self.media_root),
            }
            return CrawlRecord(record=record, discovered_links=links)

        payload_bytes = response.content
        digest = hashlib.sha256(payload_bytes).hexdigest()
        title = Path(urlparse(final_url).path).name
        tags = sorted(infer_document_tags(final_url, title=title, text=""))

        file_path: Path
        media_path: str
        should_write = True
        duplicate_pdf = False
        if extension == ".pdf":
            with self.pdf_hash_lock:
                existing_media_path = self.pdf_hash_to_media_path.get(digest)
                if existing_media_path:
                    file_path = self.media_root / existing_media_path
                    media_path = existing_media_path
                    should_write = False
                    duplicate_pdf = True
                else:
                    file_path = _build_storage_path(self.root, "files", final_url, extension)
                    media_path = rel_media_path(file_path, self.media_root)
                    self.pdf_hash_to_media_path[digest] = media_path
        else:
            file_path = _build_storage_path(self.root, "files", final_url, extension)
            media_path = rel_media_path(file_path, self.media_root)

        if not self.dry_run and should_write:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(payload_bytes)
        elif not self.dry_run and not should_write and not file_path.exists():
            # Backfill if the dedupe index pointed to a missing file.
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(payload_bytes)

        record = {
            "url": final_url,
            "source_url": source_url,
            "depth": depth,
            "resource_type": resource_type,
            "title": title,
            "tags": tags,
            "status_code": response.status_code,
            "content_type": content_type,
            "extension": extension,
            "size_bytes": len(payload_bytes),
            "sha256": digest,
            "fetched_at": fetched_at,
            "media_path": media_path,
            "is_pdf_duplicate": duplicate_pdf,
        }
        return CrawlRecord(record=record, discovered_links=[])

    def _record_failure(
        self,
        *,
        url: str,
        source_url: Optional[str],
        depth: int,
        error: str,
        status_code: Optional[int] = None,
    ) -> None:
        self.failures.append(
            {
                "url": url,
                "source_url": source_url,
                "depth": depth,
                "status_code": status_code,
                "error": error,
            }
        )

    def _create_run_record(
        self,
        *,
        run_id: str,
        started_at: dt.datetime,
    ):
        try:
            from openskagit.models import SedroWoolleyCrawlRun
        except Exception as exc:  # pragma: no cover - import safety
            LOGGER.warning("Could not import SedroWoolleyCrawlRun: %s", exc)
            return None

        defaults = {
            "start_url": self.start_url,
            "allowed_domains": sorted(self.allowed_domains),
            "max_depth": self.max_depth,
            "max_pages": self.max_pages,
            "resumed": self.resume,
            "dry_run": self.dry_run,
            "started_at": started_at,
            "finished_at": None,
            "duration_seconds": None,
            "urls_processed": 0,
            "urls_seen": 0,
            "records_written": 0,
            "html_pages": 0,
            "files": 0,
            "failure_count": 0,
            "by_resource_type": {},
            "by_extension": {},
            "tag_counts": {},
            "failures": [],
            "manifest_path": "",
            "run_summary_path": "",
        }

        try:
            run_row, _created = SedroWoolleyCrawlRun.objects.update_or_create(
                run_id=run_id,
                defaults=defaults,
            )
            return run_row
        except (OperationalError, ProgrammingError) as exc:
            LOGGER.warning("SedroWoolleyCrawlRun table not ready; skipping DB persistence: %s", exc)
            return None

    def _save_document_record(self, *, run_row, record: dict[str, Any]) -> None:
        if run_row is None:
            return

        try:
            from openskagit.models import SedroWoolleyCrawlDocument
        except Exception:
            return

        normalized_url = normalize_url(record.get("url", "")) or record.get("url", "")
        if not normalized_url:
            return

        url_hash = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
        fetched_at = _coerce_iso_datetime(record.get("fetched_at", ""))

        defaults = {
            "url": normalized_url,
            "source_url": record.get("source_url") or None,
            "depth": int(record.get("depth") or 0),
            "resource_type": str(record.get("resource_type") or ""),
            "title": str(record.get("title") or "")[:500],
            "tags": list(record.get("tags") or []),
            "status_code": record.get("status_code"),
            "content_type": str(record.get("content_type") or "")[:255],
            "extension": str(record.get("extension") or "")[:20],
            "size_bytes": int(record.get("size_bytes") or 0),
            "sha256": str(record.get("sha256") or "")[:64],
            "fetched_at": fetched_at,
            "media_path": str(record.get("media_path") or "")[:800],
            "raw_html_path": str(record.get("raw_html_path") or "")[:800],
            "text_path": str(record.get("text_path") or "")[:800],
        }

        try:
            SedroWoolleyCrawlDocument.objects.update_or_create(
                run=run_row,
                url_hash=url_hash,
                defaults=defaults,
            )
        except (OperationalError, ProgrammingError) as exc:
            LOGGER.warning("SedroWoolleyCrawlDocument persistence skipped: %s", exc)

    def _finalize_run_record(self, *, run_row, summary: CrawlSummary) -> None:
        if run_row is None:
            return

        payload = summary.to_dict()
        try:
            run_row.finished_at = _coerce_iso_datetime(payload.get("finished_at") or "")
            run_row.duration_seconds = payload.get("duration_seconds")
            run_row.urls_processed = payload.get("urls_processed") or 0
            run_row.urls_seen = payload.get("urls_seen") or 0
            run_row.records_written = payload.get("records_written") or 0
            run_row.html_pages = payload.get("html_pages") or 0
            run_row.files = payload.get("files") or 0
            run_row.failure_count = payload.get("failure_count") or 0
            run_row.by_resource_type = payload.get("by_resource_type") or {}
            run_row.by_extension = payload.get("by_extension") or {}
            run_row.tag_counts = payload.get("tag_counts") or {}
            run_row.failures = payload.get("failures") or []
            run_row.manifest_path = payload.get("manifest_path") or ""
            run_row.run_summary_path = payload.get("run_summary_path") or ""
            run_row.save(
                update_fields=[
                    "finished_at",
                    "duration_seconds",
                    "urls_processed",
                    "urls_seen",
                    "records_written",
                    "html_pages",
                    "files",
                    "failure_count",
                    "by_resource_type",
                    "by_extension",
                    "tag_counts",
                    "failures",
                    "manifest_path",
                    "run_summary_path",
                    "updated_at",
                ]
            )
        except (OperationalError, ProgrammingError) as exc:
            LOGGER.warning("Could not finalize crawl run DB record: %s", exc)
