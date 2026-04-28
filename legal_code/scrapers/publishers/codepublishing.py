from collections import deque
import os
import re
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, NavigableString, Tag

from legal_code.scrapers.base import PlaywrightClient, make_log_context
from legal_code.scrapers.config import JurisdictionConfig
from legal_code.scrapers.errors import BlockedByChallengeError
from legal_code.scrapers.errors import ParseError
from legal_code.scrapers.types import ScrapedSection

from ._utils import extract_table_rows, normalize_inline_text, normalize_multiline_text

CHAPTER_RE = re.compile(r"Chapter\s+([A-Za-z0-9.]+)\s*(.*)", flags=re.IGNORECASE)
SECTION_RE = re.compile(r"^(\d+(?:\.\d+){1,})\s*(.*)$")
SECTION_ID_VALID_RE = re.compile(r"^\d+(?:\.[0-9A-Za-z]+)+$")


def scrape(
    client: PlaywrightClient,
    jurisdiction: JurisdictionConfig,
    *,
    max_pages: Optional[int] = None,
) -> List[ScrapedSection]:
    seed_context = make_log_context(jurisdiction=jurisdiction.slug, publisher=jurisdiction.publisher)
    landing_html = client.fetch_html(jurisdiction.base_url, log_context=seed_context)
    landing_soup = BeautifulSoup(landing_html, "html.parser")

    section_urls = _extract_code_urls(
        landing_soup,
        base_url=jurisdiction.base_url,
        jurisdiction_path=_jurisdiction_path(jurisdiction.base_url),
    )
    if not section_urls:
        raise ParseError(
            "codepublishing_seed_urls_missing",
            details={"jurisdiction": jurisdiction.slug, "url": jurisdiction.base_url},
        )

    queue: Deque[str] = deque(sorted(section_urls))
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
            # Keep progress on large crawls if one page is challenged.
            if not records:
                raise
            continue
        soup = BeautifulSoup(html, "html.parser")

        for next_url in _extract_code_urls(
            soup,
            base_url=page_url,
            jurisdiction_path=_jurisdiction_path(jurisdiction.base_url),
        ):
            if next_url not in visited:
                queue.append(next_url)

        for section in _parse_section_page(soup, jurisdiction, page_url):
            key = (section.section_id, section.source_url)
            records[key] = section

    return list(records.values())


def _parse_section_page(
    soup: BeautifulSoup,
    jurisdiction: JurisdictionConfig,
    page_url: str,
) -> List[ScrapedSection]:
    main = soup.find("div", id="mainContent")
    if not isinstance(main, Tag):
        return []

    section_headers = [
        tag
        for tag in main.find_all("h3")
        if isinstance(tag, Tag) and "Cite" in (tag.get("class") or [])
    ]
    if not section_headers:
        return []

    chapter_heading = _chapter_heading(main)
    chapter_key, chapter_title = _chapter_identity(chapter_heading)

    items: List[ScrapedSection] = []
    for header in section_headers:
        section_id, heading = _section_identity(header)
        if not section_id:
            continue
        if not SECTION_ID_VALID_RE.match(section_id):
            continue

        text_chunks: List[str] = []
        history: List[str] = []
        tables: List[dict] = []

        for sibling in header.next_siblings:
            if isinstance(sibling, Tag) and sibling.name == "h3" and "Cite" in (sibling.get("class") or []):
                break
            if isinstance(sibling, NavigableString):
                continue
            if not isinstance(sibling, Tag):
                continue

            if sibling.name == "table":
                rows = extract_table_rows(sibling)
                if rows:
                    tables.append({"rows": rows})
                continue

            text = normalize_multiline_text(sibling.get_text("\n", strip=True))
            if not text:
                continue
            text_chunks.append(text)
            if "[ord." in text.lower() or text.lower().startswith("(ord."):
                history.append(text)

        section_text = "\n\n".join(text_chunks).strip()
        if not section_text and not tables:
            continue

        source_url = f"{page_url}#{section_id}"
        chapter_key_value = chapter_key or _chapter_from_section_id(section_id)
        chapter_title_value = chapter_title or chapter_heading or "Chapter"

        items.append(
            ScrapedSection(
                jurisdiction_slug=jurisdiction.slug,
                jurisdiction_name=jurisdiction.name,
                source_vendor=jurisdiction.publisher,
                document_key="ALL",
                document_title=f"{jurisdiction.name} Code",
                chapter_key=chapter_key_value,
                chapter_title=chapter_title_value,
                section_id=section_id,
                section_heading=heading,
                section_text=section_text,
                section_history=history,
                section_tables=tables,
                source_url=source_url,
            )
        )

    return items


def _jurisdiction_path(base_url: str) -> str:
    parsed = urlparse(base_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return f"/{parts[0]}/{parts[1]}/"
    return parsed.path


def _extract_code_urls(soup: BeautifulSoup, *, base_url: str, jurisdiction_path: str) -> Set[str]:
    urls: Set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue

        for candidate in _candidate_urls(href, base_url=base_url, jurisdiction_path=jurisdiction_path):
            if candidate:
                urls.add(candidate)
    return urls


def _candidate_urls(href: str, *, base_url: str, jurisdiction_path: str) -> Iterable[str]:
    if "#!/" in href:
        fragment = href.split("#!/", 1)[1]
        fragment = fragment.split("?", 1)[0].strip("/")
        if fragment.lower().endswith(".html"):
            yield _normalize_url(urljoin(base_url, f"html/{fragment}"))
        return

    absolute = urljoin(base_url, href)
    normalized = _normalize_url(absolute)
    parsed = urlparse(normalized)
    if parsed.netloc != "www.codepublishing.com":
        return
    if not parsed.path.endswith(".html"):
        return

    if f"{jurisdiction_path}html/" not in parsed.path and not parsed.path.startswith(
        f"{jurisdiction_path}html/"
    ):
        return
    yield normalized


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment="", query=""))


def _chapter_heading(main: Tag) -> str:
    chapter = main.find("h2", class_=lambda value: value and "CH" in value)
    if isinstance(chapter, Tag):
        return normalize_inline_text(chapter.get_text(" ", strip=True))
    return ""


def _chapter_identity(chapter_heading: str) -> Tuple[str, str]:
    if not chapter_heading:
        return "", ""
    match = CHAPTER_RE.search(chapter_heading)
    if not match:
        return "", chapter_heading
    chapter_key = normalize_inline_text(match.group(1))
    chapter_title = normalize_inline_text(match.group(2)) or chapter_heading
    return chapter_key, chapter_title


def _section_identity(header: Tag) -> Tuple[str, str]:
    section_id = normalize_inline_text((header.get("id") or ""))
    text = normalize_inline_text(header.get_text(" ", strip=True))

    if not section_id:
        match = SECTION_RE.match(text)
        if match:
            section_id = normalize_inline_text(match.group(1))

    heading = text
    if section_id and heading.startswith(section_id):
        heading = normalize_inline_text(heading[len(section_id) :])
    if not heading:
        heading = section_id

    return section_id, heading


def _chapter_from_section_id(section_id: str) -> str:
    parts = section_id.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return section_id
