import base64
import json
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from mcp_agent.legal.utils import normalize_inline_text, normalize_multiline_text

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OpenSkagitLegal/1.0"
)
DEFAULT_TIMEOUT = (5, 20)
ID_PREFIX = "ec"
DOC_ID_RE = re.compile(r"^/\d{5,}$")


class UpstreamFetchError(RuntimeError):
    pass


class UpstreamParseError(RuntimeError):
    pass


def search(jurisdiction: Dict[str, object], q: str, limit: int) -> List[Dict[str, object]]:
    base_url = str(jurisdiction["base_url"]).rstrip("/")
    search_url = f"{base_url}/search?query={quote(q)}&scope=all&sortOrder=relevance"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": base_url,
    }
    try:
        resp = requests.get(search_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamFetchError(f"search_request_failed: {exc}") from exc

    if resp.status_code != 200:
        if resp.status_code == 403 and "cf-mitigated" in {k.lower() for k in resp.headers.keys()}:
            raise UpstreamFetchError("search_blocked_by_cloudflare")
        raise UpstreamFetchError(f"search_http_{resp.status_code}")

    try:
        return _parse_search_results(resp.text, jurisdiction, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise UpstreamParseError(f"search_parse_failed: {exc}") from exc


def get(jurisdiction: Dict[str, object], id_value: str) -> Dict[str, object]:
    slug, doc_path = _parse_id(id_value)
    expected_slug = str(jurisdiction["slug"])
    if slug != expected_slug:
        raise ValueError("id_jurisdiction_mismatch")

    base_origin = f"{urlparse(str(jurisdiction['base_url'])).scheme}://{urlparse(str(jurisdiction['base_url'])).netloc}"
    doc_url = urljoin(base_origin, doc_path)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": str(jurisdiction["base_url"]),
    }
    try:
        resp = requests.get(doc_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamFetchError(f"get_request_failed: {exc}") from exc

    if resp.status_code != 200:
        if resp.status_code == 403 and "cf-mitigated" in {k.lower() for k in resp.headers.keys()}:
            raise UpstreamFetchError("get_blocked_by_cloudflare")
        raise UpstreamFetchError(f"get_http_{resp.status_code}")

    try:
        return _parse_document(resp.text, doc_url)
    except Exception as exc:  # noqa: BLE001
        raise UpstreamParseError(f"get_parse_failed: {exc}") from exc


def _make_id(slug: str, doc_path: str) -> str:
    payload = {"p": doc_path}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"{ID_PREFIX}:{slug}:{token}"


def _parse_id(id_value: str) -> Tuple[str, str]:
    parts = id_value.split(":", 2)
    if len(parts) != 3 or parts[0] != ID_PREFIX:
        raise ValueError("invalid_id_format")

    slug = parts[1].strip().lower()
    token = parts[2].strip()
    if not slug or not token:
        raise ValueError("invalid_id_format")

    pad = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode((token + pad).encode("utf-8")).decode("utf-8")
        payload = json.loads(decoded)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_id_payload") from exc

    doc_path = (payload.get("p") or "").strip()
    if not doc_path:
        raise ValueError("invalid_id_payload")
    return slug, doc_path


def _parse_search_results(html: str, jurisdiction: Dict[str, object], limit: int) -> List[Dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    base_origin = f"{urlparse(str(jurisdiction['base_url'])).scheme}://{urlparse(str(jurisdiction['base_url'])).netloc}"
    hits: List[Dict[str, object]] = []
    seen_paths = set()

    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not DOC_ID_RE.match(href):
            continue
        if href in seen_paths:
            continue
        seen_paths.add(href)

        heading = normalize_inline_text(anchor.get_text(" ", strip=True))
        if not heading:
            continue

        parent_text = normalize_inline_text((anchor.parent.get_text(" ", strip=True) if anchor.parent else ""))
        snippet = parent_text if parent_text and parent_text != heading else ""
        url = urljoin(base_origin, href)
        hits.append(
            {
                "id": _make_id(str(jurisdiction["slug"]), href),
                "cite": _derive_cite(heading),
                "heading": heading,
                "snippet": snippet,
                "url": url,
            }
        )
        if len(hits) >= limit:
            break

    if not hits:
        # Challenge page or format drift.
        if "Just a moment..." in (soup.title.get_text(strip=True) if soup.title else ""):
            raise UpstreamParseError("search_blocked_by_cloudflare")
    return hits


def _parse_document(html: str, doc_url: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_inline_text((soup.title.get_text(" ", strip=True) if soup.title else ""))
    if title == "Just a moment...":
        raise UpstreamParseError("get_blocked_by_cloudflare")

    # Ecode360 pages vary; prefer semantic containers.
    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find("section", attrs={"id": "content"})
        or soup.find("div", attrs={"id": "content"})
        or soup.body
    )
    if not isinstance(container, Tag):
        raise UpstreamParseError("content_container_missing")

    text = normalize_multiline_text(container.get_text("\n", strip=True))
    if not text:
        raise UpstreamParseError("document_text_empty")

    cite = _derive_cite(title) or _derive_cite(text.splitlines()[0] if text else "")
    return {"cite": cite, "text": text, "url": doc_url}


def _derive_cite(text: str) -> Optional[str]:
    if not text:
        return None
    chapter_match = re.search(r"\b(?:Chapter|CH)\s+(\d+(?:\.\d+)*)\b", text, flags=re.IGNORECASE)
    if chapter_match:
        return chapter_match.group(0)
    section_match = re.search(r"\b\d+(?:\.\d+){1,}\b", text)
    if section_match:
        return section_match.group(0)
    return None

