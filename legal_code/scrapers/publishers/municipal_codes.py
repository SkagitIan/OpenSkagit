from collections import deque
import re
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from legal_code.scrapers.base import PlaywrightClient, make_log_context
from legal_code.scrapers.config import JurisdictionConfig
from legal_code.scrapers.errors import BlockedByChallengeError
from legal_code.scrapers.types import ScrapedSection

from ._utils import extract_table_rows, normalize_inline_text, normalize_multiline_text

SECTION_ID_RE = re.compile(r"^\d+(?:\.\d+)+$")
TITLE_RE = re.compile(r"Title\s+([A-Za-z0-9.\-]+)\s*(.*)", flags=re.IGNORECASE)


def scrape(
    client: PlaywrightClient,
    jurisdiction: JurisdictionConfig,
    *,
    max_pages: Optional[int] = None,
) -> List[ScrapedSection]:
    queue: Deque[str] = deque([_normalize_url(jurisdiction.base_url)])
    visited: Set[str] = set()
    records: Dict[Tuple[str, str], ScrapedSection] = {}

    while queue:
        if max_pages is not None and len(visited) >= max_pages:
            break

        page_url = queue.popleft()
        if page_url in visited:
            continue
        visited.add(page_url)

        try:
            html = client.fetch_html(
                page_url,
                log_context=make_log_context(
                    jurisdiction=jurisdiction.slug,
                    publisher=jurisdiction.publisher,
                    url=page_url,
                ),
            )
        except BlockedByChallengeError:
            if not records:
                raise
            continue
        soup = BeautifulSoup(html, "html.parser")

        for next_url in _extract_municipal_urls(soup, base_url=page_url, jurisdiction=jurisdiction):
            if next_url not in visited:
                queue.append(next_url)

        for section in _parse_sections_from_page(soup, jurisdiction, page_url):
            records[(section.section_id, section.source_url)] = section

    return list(records.values())


def _extract_municipal_urls(
    soup: BeautifulSoup,
    *,
    base_url: str,
    jurisdiction: JurisdictionConfig,
) -> Iterable[str]:
    base_host = urlparse(jurisdiction.base_url).netloc
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue

        absolute = _normalize_url(urljoin(base_url, href))
        parsed = urlparse(absolute)
        if parsed.netloc != base_host:
            continue

        path = parsed.path
        if not path.startswith("/AMC"):
            continue
        if path.lower().startswith("/amc/search"):
            continue
        if path.lower().startswith("/amc/contents"):
            continue
        yield absolute


def _parse_sections_from_page(
    soup: BeautifulSoup,
    jurisdiction: JurisdictionConfig,
    page_url: str,
) -> List[ScrapedSection]:
    title_text = normalize_inline_text((soup.title.get_text(" ", strip=True) if soup.title else ""))
    document_key, document_title = _document_identity(title_text)

    sections: List[ScrapedSection] = []
    for section in soup.select("article.type-Section"):
        if not isinstance(section, Tag):
            continue

        section_id = normalize_inline_text(section.get("id") or "")
        if not section_id or not SECTION_ID_RE.match(section_id):
            continue

        chapter = section.find_parent("article", class_="type-Chapter")
        chapter_key, chapter_title = _chapter_identity(chapter, section_id)

        heading_tag = section.find(["h6", "h5", "h4", "h3"])
        heading = normalize_inline_text(heading_tag.get_text(" ", strip=True) if heading_tag else section_id)

        text_parts: List[str] = []
        history: List[str] = []
        tables: List[dict] = []

        for table in section.find_all("table"):
            rows = extract_table_rows(table)
            if rows:
                tables.append({"rows": rows})

        for para in section.find_all("p"):
            text = normalize_multiline_text(para.get_text("\n", strip=True))
            if not text:
                continue
            text_parts.append(text)
            history_nodes = para.find_all("span", class_="note history")
            for node in history_nodes:
                history_text = normalize_inline_text(node.get_text(" ", strip=True))
                if history_text:
                    history.append(history_text)

        section_text = "\n\n".join(text_parts).strip()
        if not section_text and not tables:
            continue

        source_url = urljoin(jurisdiction.base_url, f"AMC/{section_id}")
        sections.append(
            ScrapedSection(
                jurisdiction_slug=jurisdiction.slug,
                jurisdiction_name=jurisdiction.name,
                source_vendor=jurisdiction.publisher,
                document_key=document_key,
                document_title=document_title,
                chapter_key=chapter_key,
                chapter_title=chapter_title,
                section_id=section_id,
                section_heading=heading,
                section_text=section_text,
                section_history=history,
                section_tables=tables,
                source_url=source_url,
            )
        )

    return sections


def _document_identity(title_text: str) -> Tuple[str, str]:
    match = TITLE_RE.search(title_text)
    if not match:
        return "ALL", title_text or "Municipal Code"
    key = normalize_inline_text(match.group(1))
    name = normalize_inline_text(match.group(2))
    return key or "ALL", title_text if not name else f"Title {key} {name}".strip()


def _chapter_identity(chapter: Optional[Tag], section_id: str) -> Tuple[str, str]:
    if isinstance(chapter, Tag):
        chapter_id = normalize_inline_text(chapter.get("id") or "")
        chapter_header = chapter.find(["h4", "h3"])
        chapter_title = normalize_inline_text(
            chapter_header.get_text(" ", strip=True) if isinstance(chapter_header, Tag) else ""
        )
        if chapter_id:
            return chapter_id, chapter_title or chapter_id

    parts = section_id.split(".")
    if len(parts) >= 2:
        key = ".".join(parts[:2])
        return key, f"Chapter {key}"
    return section_id, section_id


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment="", query=""))
