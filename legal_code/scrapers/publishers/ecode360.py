from collections import deque
import re
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from legal_code.scrapers.base import PlaywrightClient, make_log_context
from legal_code.scrapers.config import JurisdictionConfig
from legal_code.scrapers.errors import BlockedByChallengeError
from legal_code.scrapers.types import ScrapedSection

from ._utils import normalize_inline_text, normalize_multiline_text

CITE_RE = re.compile(r"\b(\d+(?:\.\d+){1,})\b")
STATIC_EXT_RE = re.compile(r"\.(?:css|js|png|jpg|jpeg|gif|svg|ico|woff|woff2|map|json|pdf)$", flags=re.IGNORECASE)


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

        for next_url in _extract_internal_urls(soup, base_url=page_url, jurisdiction=jurisdiction):
            if next_url not in visited:
                queue.append(next_url)

        section = _parse_section_page(soup, jurisdiction, page_url)
        if section is not None:
            records[(section.section_id, section.source_url)] = section

    return list(records.values())


def _extract_internal_urls(
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
        if href.lower().startswith("javascript:"):
            continue

        absolute = _normalize_url(urljoin(base_url, href))
        parsed = urlparse(absolute)
        if parsed.netloc != base_host:
            continue

        path = parsed.path or ""
        if not path.startswith("/"):
            continue
        if path.startswith("/cdn-cgi/"):
            continue
        if STATIC_EXT_RE.search(path):
            continue

        if path == "/":
            continue
        yield absolute


def _parse_section_page(
    soup: BeautifulSoup,
    jurisdiction: JurisdictionConfig,
    page_url: str,
) -> Optional[ScrapedSection]:
    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find("section", attrs={"id": "content"})
        or soup.find("div", attrs={"id": "content"})
        or soup.body
    )
    if not isinstance(container, Tag):
        return None

    text = normalize_multiline_text(container.get_text("\n", strip=True))
    if not text:
        return None

    title_text = normalize_inline_text((soup.title.get_text(" ", strip=True) if soup.title else ""))
    heading_tag = container.find(["h1", "h2", "h3"])
    heading = normalize_inline_text(heading_tag.get_text(" ", strip=True) if isinstance(heading_tag, Tag) else "")
    if not heading:
        heading = title_text

    cite = _extract_cite(heading) or _extract_cite(title_text) or _extract_cite(text.split("\n", 1)[0])

    section_id = cite or _path_token(page_url)
    if not section_id:
        return None

    chapter_key, chapter_title = _chapter_identity(section_id, heading)

    return ScrapedSection(
        jurisdiction_slug=jurisdiction.slug,
        jurisdiction_name=jurisdiction.name,
        source_vendor=jurisdiction.publisher,
        document_key="ALL",
        document_title=f"{jurisdiction.name} Code",
        chapter_key=chapter_key,
        chapter_title=chapter_title,
        section_id=section_id,
        section_heading=heading or section_id,
        section_text=text,
        source_url=page_url,
    )


def _extract_cite(text: str) -> str:
    if not text:
        return ""
    match = CITE_RE.search(text)
    return normalize_inline_text(match.group(1)) if match else ""


def _chapter_identity(section_id: str, heading: str) -> Tuple[str, str]:
    parts = section_id.split(".")
    if len(parts) >= 2:
        key = ".".join(parts[:2])
        title = heading or f"Chapter {key}"
        return key, title
    return section_id, heading or section_id


def _path_token(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if not path:
        return ""
    token = path.split("/")[-1]
    return normalize_inline_text(token)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment="", query=""))
