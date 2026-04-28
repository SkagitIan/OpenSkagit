import base64
import json
import re
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

from mcp_agent.legal.utils import normalize_inline_text, normalize_multiline_text

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OpenSkagitLegal/1.0"
)
DEFAULT_TIMEOUT = (5, 20)
ID_PREFIX = "wa"
SEARCH_URL = "https://search.leg.wa.gov/SearchTermHandler.ashx?MethodName=Search"
RCW_DOC_BASE = "https://app.leg.wa.gov/RCW/default.aspx?cite="
CITE_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)*)\b")


class UpstreamFetchError(RuntimeError):
    pass


class UpstreamParseError(RuntimeError):
    pass


def search(jurisdiction: Dict[str, object], q: str, limit: int) -> List[Dict[str, object]]:
    payload = {
        "Query": q,
        "DocLike": "",
        "ResultsPerPage": str(limit),
        "MaxDocs": "1000",
        "Proximity": "5",
        "SortBy": "radioBtnRankSort",
        "Agency": "",
        "Bienniums": [],
        "Years": [],
        "LawDocs": ["RCW"],
        "BienniumDocs": [],
        "YearlyDocs": [],
        "WebDocs": [],
        "Zones": [],
        "Page": 1,
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Origin": "https://search.leg.wa.gov",
        "Referer": "https://search.leg.wa.gov/search.aspx",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    try:
        resp = requests.post(SEARCH_URL, headers=headers, data=json.dumps(payload), timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamFetchError(f"search_request_failed: {exc}") from exc

    if resp.status_code != 200:
        raise UpstreamFetchError(f"search_http_{resp.status_code}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise UpstreamParseError("search_non_json_response") from exc

    if not body.get("Success"):
        err = body.get("Error") or {}
        message = normalize_inline_text(str(err.get("Message") or "search_failed"))
        raise UpstreamFetchError(message or "search_failed")

    response_html = body.get("Response") or ""
    try:
        return _parse_search_response(response_html, jurisdiction=jurisdiction, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise UpstreamParseError(f"search_parse_failed: {exc}") from exc


def get(jurisdiction: Dict[str, object], id_value: str) -> Dict[str, object]:
    slug, cite = _parse_id(id_value)
    expected_slug = str(jurisdiction["slug"])
    if slug != expected_slug:
        raise ValueError("id_jurisdiction_mismatch")

    doc_url = f"{RCW_DOC_BASE}{cite}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://app.leg.wa.gov/RCW/",
    }
    try:
        resp = requests.get(doc_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamFetchError(f"get_request_failed: {exc}") from exc

    if resp.status_code != 200:
        raise UpstreamFetchError(f"get_http_{resp.status_code}")

    try:
        return _parse_document(resp.text, jurisdiction=jurisdiction, cite=cite, doc_url=doc_url)
    except Exception as exc:  # noqa: BLE001
        raise UpstreamParseError(f"get_parse_failed: {exc}") from exc


def _make_id(slug: str, cite: str) -> str:
    payload = {"cite": cite}
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

    cite = normalize_inline_text(str(payload.get("cite") or ""))
    if not cite:
        raise ValueError("invalid_id_payload")
    return slug, cite


def _parse_search_response(
    response_html: str, jurisdiction: Dict[str, object], limit: int
) -> List[Dict[str, object]]:
    soup = BeautifulSoup(response_html, "html.parser")
    hits: List[Dict[str, object]] = []

    for row in soup.select("div.searchResultRowClass"):
        anchor = row.select_one("a.searchResultDisplayNameClass")
        if not isinstance(anchor, Tag):
            continue

        anchor_text = normalize_inline_text(anchor.get_text(" ", strip=True))
        if not anchor_text:
            continue

        cite = _extract_cite(anchor_text)
        if not cite:
            continue

        row_text = normalize_inline_text(row.get_text(" ", strip=True))
        snippet = row_text
        if row_text.startswith(anchor_text):
            snippet = normalize_inline_text(row_text[len(anchor_text) :])

        heading = anchor_text
        hits.append(
            {
                "id": _make_id(str(jurisdiction["slug"]), cite),
                "cite": anchor_text,
                "heading": heading,
                "snippet": snippet,
                "url": f"{RCW_DOC_BASE}{cite}",
            }
        )
        if len(hits) >= limit:
            break

    return hits


def _parse_document(
    html: str, jurisdiction: Dict[str, object], cite: str, doc_url: str
) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    wrapper = soup.find("div", id="contentWrapper") or soup.find("div", id="divContent") or soup.body
    if not isinstance(wrapper, Tag):
        raise UpstreamParseError("content_container_missing")

    blocks = []
    for div in wrapper.find_all("div", recursive=False):
        text = normalize_multiline_text(div.get_text("\n", strip=True))
        if text:
            blocks.append(text)

    if not blocks:
        fallback = normalize_multiline_text(wrapper.get_text("\n", strip=True))
        if not fallback:
            raise UpstreamParseError("document_text_empty")
        blocks = [fallback]

    text = "\n\n".join(blocks)
    neighbors = _extract_neighbors(soup, slug=str(jurisdiction["slug"]))

    result: Dict[str, object] = {
        "cite": f"RCW {cite}",
        "text": text,
        "url": doc_url,
    }
    if neighbors:
        result["neighbors"] = neighbors
    return result


def _extract_neighbors(soup: BeautifulSoup, slug: str) -> Optional[Dict[str, str]]:
    panel = soup.find("div", id="ContentPlaceHolder1_pnlPrevNext")
    if not isinstance(panel, Tag):
        return None

    values: List[str] = []
    for anchor in panel.find_all("a"):
        label = normalize_inline_text(anchor.get_text(" ", strip=True))
        cite = _extract_cite(label)
        if cite:
            values.append(cite)

    if len(values) < 3:
        return None

    center = values[1]
    if not center:
        return None

    payload: Dict[str, str] = {}
    prev_cite = values[0]
    next_cite = values[2]
    if prev_cite:
        payload["prev"] = _make_id(slug, prev_cite)
    if next_cite:
        payload["next"] = _make_id(slug, next_cite)
    return payload or None


def _extract_cite(text: str) -> Optional[str]:
    if not text:
        return None
    match = CITE_RE.search(text)
    if not match:
        return None
    return match.group(1)
