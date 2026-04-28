import json
import math
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup, Tag

from legal_code.scrapers.base import PlaywrightClient, make_log_context
from legal_code.scrapers.config import JurisdictionConfig
from legal_code.scrapers.errors import ParseError
from legal_code.scrapers.types import ScrapedSection

from ._utils import normalize_inline_text, normalize_multiline_text

SEARCH_URL = "https://search.leg.wa.gov/SearchTermHandler.ashx?MethodName=Search"
GET_URL = "https://search.leg.wa.gov/SearchTermHandler.ashx?MethodName=GetDocument&Type=Content"
RESULTS_PER_PAGE = 50
LAW_DOCS = ["RCW", "RCWDisposition", "Ethic", "Constitution", "WAC"]
DOC_LABEL_RE = re.compile(
    r"\b(RCW|WAC|Constitution|Ethic(?:s)?|RCWDisposition)\b(?:\s+(.+))?",
    flags=re.IGNORECASE,
)
RCW_ID_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)*)\b")
WAC_ID_RE = re.compile(r"\b(\d{1,4}(?:-\d{1,4}){1,3})\b")


def scrape(
    client: PlaywrightClient,
    jurisdiction: JurisdictionConfig,
    *,
    max_pages: Optional[int] = None,
) -> List[ScrapedSection]:
    context = client.new_context(user_agent=jurisdiction.scrape_settings.user_agent)
    try:
        # Prime cookies/session from the search UI before API-style calls.
        client.fetch_html(
            jurisdiction.base_url,
            context=context,
            log_context=make_log_context(
                jurisdiction=jurisdiction.slug,
                publisher=jurisdiction.publisher,
                url=jurisdiction.base_url,
            ),
        )

        page_number = 1
        total_pages: Optional[int] = None
        seen_tokens: Set[str] = set()
        records: Dict[Tuple[str, str], ScrapedSection] = {}

        while True:
            if max_pages is not None and page_number > max_pages:
                break
            if total_pages is not None and page_number > total_pages:
                break

            payload = _search_payload(page_number)
            body = json.dumps(payload, separators=(",", ":"))
            response = client.request_json(
                SEARCH_URL,
                method="POST",
                data=body,
                headers=_search_headers(),
                context=context,
                log_context=make_log_context(
                    jurisdiction=jurisdiction.slug,
                    publisher=jurisdiction.publisher,
                    document="search_page",
                    section_id=str(page_number),
                    url=SEARCH_URL,
                ),
            )

            if not response.get("Success"):
                error = response.get("Error") or {}
                message = normalize_inline_text(str(error.get("Message") or "wa_search_failed"))
                raise ParseError(
                    "wa_search_failed",
                    details={"page": page_number, "reason": message},
                )

            response_html = response.get("Response") or ""
            soup = BeautifulSoup(response_html, "html.parser")
            rows = soup.select("div.searchResultRowClass")
            if not rows:
                break

            if total_pages is None:
                total_pages = _extract_total_pages(soup)

            for row in rows:
                checkbox = row.select_one("input.searchResultChkBoxClass")
                anchor = row.select_one("a.searchResultDisplayNameClass")
                if not isinstance(checkbox, Tag) or not isinstance(anchor, Tag):
                    continue

                token = normalize_inline_text(checkbox.get("value") or "")
                cite_label = normalize_inline_text(anchor.get_text(" ", strip=True))
                if not token or token in seen_tokens:
                    continue

                seen_tokens.add(token)
                document_html = _fetch_document_html(
                    client,
                    context=context,
                    token=token,
                    jurisdiction=jurisdiction,
                )
                section = _parse_document(
                    document_html,
                    jurisdiction=jurisdiction,
                    fallback_cite=cite_label,
                )
                if section is None:
                    continue
                records[(section.section_id, section.source_url)] = section

            page_number += 1

        return list(records.values())
    finally:
        context.close()


def _search_payload(page_number: int) -> Dict[str, object]:
    return {
        "Query": "*",
        "DocLike": "",
        "ResultsPerPage": str(RESULTS_PER_PAGE),
        "MaxDocs": "50000",
        "Proximity": "5",
        "SortBy": "radioBtnRankSort",
        "Agency": "",
        "Bienniums": [],
        "Years": [],
        "LawDocs": LAW_DOCS,
        "BienniumDocs": [],
        "YearlyDocs": [],
        "WebDocs": [],
        "Zones": [],
        "Page": page_number,
    }


def _search_headers() -> Dict[str, str]:
    return {
        "Accept": "*/*",
        "Origin": "https://search.leg.wa.gov",
        "Referer": "https://search.leg.wa.gov/search.aspx",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }


def _fetch_document_html(
    client: PlaywrightClient,
    *,
    context,
    token: str,
    jurisdiction: JurisdictionConfig,
) -> str:
    encoded = quote(quote(token, safe=""), safe="")
    body = f"DocumentQuery={encoded}"
    response = client.request_json(
        GET_URL,
        method="POST",
        data=body,
        headers=_search_headers(),
        context=context,
        log_context=make_log_context(
            jurisdiction=jurisdiction.slug,
            publisher=jurisdiction.publisher,
            document="get_document",
            url=GET_URL,
        ),
    )
    if not response.get("Success"):
        error = response.get("Error") or {}
        message = normalize_inline_text(str(error.get("Message") or "wa_get_document_failed"))
        raise ParseError("wa_get_document_failed", details={"reason": message})

    return str(response.get("Response") or "")


def _parse_document(
    html: str,
    *,
    jurisdiction: JurisdictionConfig,
    fallback_cite: str,
) -> Optional[ScrapedSection]:
    soup = BeautifulSoup(html, "html.parser")
    cite_label, heading = _heading_parts(soup, fallback_cite)

    doc_type, section_id = _doc_identity(cite_label)
    if not section_id:
        return None

    source_url = _canonical_source_url(soup, doc_type=doc_type, section_id=section_id)
    chapter_key, chapter_title = _chapter_identity(doc_type, section_id, heading)

    text = _extract_text_block(soup)
    if not text:
        return None

    return ScrapedSection(
        jurisdiction_slug=jurisdiction.slug,
        jurisdiction_name=jurisdiction.name,
        source_vendor=jurisdiction.publisher,
        document_key=doc_type,
        document_title=f"Washington {doc_type}",
        chapter_key=chapter_key,
        chapter_title=chapter_title,
        section_id=section_id,
        section_heading=heading or cite_label,
        section_text=text,
        source_url=source_url,
    )


def _heading_parts(soup: BeautifulSoup, fallback_cite: str) -> Tuple[str, str]:
    headers = [normalize_inline_text(h.get_text(" ", strip=True)) for h in soup.find_all("h3")]
    headers = [header for header in headers if header]
    if not headers:
        return fallback_cite, fallback_cite

    cite_label = fallback_cite
    heading = headers[0]
    for idx, header in enumerate(headers):
        if DOC_LABEL_RE.match(header) or RCW_ID_RE.search(header) or WAC_ID_RE.search(header):
            cite_label = header
            if idx + 1 < len(headers):
                heading = headers[idx + 1]
            else:
                heading = header
            break
    return cite_label or fallback_cite, heading


def _doc_identity(cite_label: str) -> Tuple[str, str]:
    label = normalize_inline_text(cite_label)
    label = re.sub(r"^PDF\s+", "", label, flags=re.IGNORECASE)
    match = DOC_LABEL_RE.search(label)
    if match:
        doc_type = normalize_inline_text(match.group(1)).upper()
        raw_ref = normalize_inline_text(match.group(2) or "")
    else:
        doc_type = "LAW"
        raw_ref = label

    if doc_type.startswith("ETHIC"):
        doc_type = "ETHIC"

    if doc_type == "RCW":
        rcw_match = RCW_ID_RE.search(raw_ref or label)
        return doc_type, rcw_match.group(1) if rcw_match else raw_ref

    if doc_type == "WAC":
        wac_match = WAC_ID_RE.search(raw_ref or label)
        return doc_type, wac_match.group(1) if wac_match else raw_ref

    section_id = re.sub(r"\s+", "_", raw_ref).strip("_")
    return doc_type, section_id


def _chapter_identity(doc_type: str, section_id: str, heading: str) -> Tuple[str, str]:
    if doc_type == "RCW":
        parts = section_id.split(".")
        if len(parts) >= 2:
            key = ".".join(parts[:2])
            return key, heading or f"Chapter {key}"

    if doc_type == "WAC":
        parts = section_id.split("-")
        if len(parts) >= 2:
            key = "-".join(parts[:2])
            return key, heading or f"Chapter {key}"

    return doc_type, heading or doc_type


def _canonical_source_url(soup: BeautifulSoup, *, doc_type: str, section_id: str) -> str:
    for anchor in soup.find_all("a", href=True):
        href = normalize_inline_text(anchor.get("href") or "")
        if not href:
            continue
        if "app.leg.wa.gov" not in href.lower():
            continue

        url = href.replace("http://", "https://")
        if "&pdf=true" in url.lower():
            url = re.sub(r"&pdf=true", "", url, flags=re.IGNORECASE)
        return url

    if doc_type == "RCW":
        return f"https://app.leg.wa.gov/RCW/default.aspx?cite={section_id}"
    if doc_type == "WAC":
        return f"https://app.leg.wa.gov/WAC/default.aspx?cite={section_id}"
    return "https://app.leg.wa.gov/"


def _extract_text_block(soup: BeautifulSoup) -> str:
    body = soup.body if isinstance(soup.body, Tag) else None
    if not body:
        return ""

    candidates: List[str] = []
    for div in body.find_all("div"):
        if div.find("h3"):
            continue
        text = normalize_multiline_text(div.get_text("\n", strip=True))
        if text:
            candidates.append(text)

    if candidates:
        return max(candidates, key=len)

    return normalize_multiline_text(body.get_text("\n", strip=True))


def _extract_total_pages(soup: BeautifulSoup) -> Optional[int]:
    total_input = soup.find("input", attrs={"id": "hdnTotalResultCount"})
    if not isinstance(total_input, Tag):
        return None

    raw = normalize_inline_text(total_input.get("value") or "")
    if not raw.isdigit():
        return None

    total = int(raw)
    if total <= 0:
        return 0
    return math.ceil(total / RESULTS_PER_PAGE)
