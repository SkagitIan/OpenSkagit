import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from legal_code.scrapers.types import ScrapedSection
from legal_code.scrapers.publishers._utils import extract_table_rows, normalize_inline_text, normalize_multiline_text

ANACORTES_BASE_URL = "https://anacortes.municipal.codes/"
BURLINGTON_BASE_URL = "https://ecode360.com/BU4372"

CHAPTER_LINE_RE = re.compile(r"^CHAPTER\s+([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)\s*$", flags=re.IGNORECASE)
SECTION_LINE_RE = re.compile(
    r"^§\s*([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)\.\s*(.*)$",
    flags=re.IGNORECASE,
)
BURLINGTON_FOOTER_RE = re.compile(r"^Downloaded from https?://", flags=re.IGNORECASE)
BURLINGTON_HEADER_RE = re.compile(r"^[A-Z0-9 ,&().\-]+\s+§\s+[0-9A-Za-z.]+$")


def parse_anacortes_html_snapshot(path: str | Path) -> List[ScrapedSection]:
    source_path = Path(path)
    soup = BeautifulSoup(source_path.read_text(encoding="utf-8"), "html.parser")

    main = soup.find("main", id="main")
    if not isinstance(main, Tag):
        raise ValueError(f"main#main not found in {source_path}")

    sections: List[ScrapedSection] = []
    for chapter in main.find_all("article", class_="type-Chapter", recursive=True):
        if not isinstance(chapter, Tag):
            continue

        chapter_key, chapter_title = _anacortes_chapter_identity(chapter)
        for section in chapter.find_all("article", class_="type-Section", recursive=False):
            if not isinstance(section, Tag):
                continue

            section_id_raw = normalize_inline_text(section.get("id") or "")
            section_id = _strip_anacortes_prefix(section_id_raw)
            if not section_id:
                continue

            heading = _anacortes_section_heading(section, section_id)
            text_parts: List[str] = []
            history: List[str] = []
            tables: List[Dict[str, object]] = []

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
                    hist_text = normalize_inline_text(node.get_text(" ", strip=True))
                    if hist_text:
                        history.append(hist_text)

            section_text = "\n\n".join(text_parts).strip()
            if not section_text and not tables:
                continue

            sections.append(
                ScrapedSection(
                    jurisdiction_slug="anacortes",
                    jurisdiction_name="City of Anacortes",
                    source_vendor="municipal_codes",
                    document_key="ALL",
                    document_title="Anacortes Municipal Code",
                    chapter_key=chapter_key,
                    chapter_title=chapter_title,
                    section_id=section_id,
                    section_heading=heading,
                    section_text=section_text,
                    section_history=history,
                    section_tables=tables,
                    source_url=f"{ANACORTES_BASE_URL}AMC/{section_id}",
                )
            )

    return sections


def parse_burlington_pdf_snapshot(path: str | Path) -> List[ScrapedSection]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("pypdf is required to parse Burlington PDF snapshots") from exc

    source_path = Path(path)
    reader = PdfReader(str(source_path))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return _parse_burlington_pages_text(pages_text)


def _parse_burlington_pages_text(pages_text: Iterable[str]) -> List[ScrapedSection]:
    sections: List[ScrapedSection] = []

    chapter_key = ""
    chapter_title = ""
    waiting_for_chapter_title = False

    current_section_id = ""
    current_section_heading = ""
    current_body: List[str] = []

    def flush_section() -> None:
        nonlocal current_section_id, current_section_heading, current_body
        if not current_section_id:
            return

        body_lines = _clean_burlington_lines(current_body)
        section_text = "\n".join(body_lines).strip()
        if not section_text:
            current_section_id = ""
            current_section_heading = ""
            current_body = []
            return

        effective_chapter_key = chapter_key or _chapter_from_section_id(current_section_id)
        effective_chapter_title = chapter_title or f"Chapter {effective_chapter_key}"

        sections.append(
            ScrapedSection(
                jurisdiction_slug="burlington",
                jurisdiction_name="City of Burlington",
                source_vendor="ecode360",
                document_key="ALL",
                document_title="Burlington Municipal Code",
                chapter_key=effective_chapter_key,
                chapter_title=effective_chapter_title,
                section_id=current_section_id,
                section_heading=current_section_heading or current_section_id,
                section_text=section_text,
                source_url=f"{BURLINGTON_BASE_URL}",
            )
        )

        current_section_id = ""
        current_section_heading = ""
        current_body = []

    for page_text in pages_text:
        raw_lines = page_text.splitlines()
        for raw in raw_lines:
            line = normalize_inline_text(raw)
            if not line:
                continue
            if _is_burlington_noise(line):
                continue

            chapter_match = CHAPTER_LINE_RE.match(line)
            if chapter_match:
                chapter_key = normalize_inline_text(chapter_match.group(1))
                chapter_title = ""
                waiting_for_chapter_title = True
                flush_section()
                continue

            if waiting_for_chapter_title:
                if SECTION_LINE_RE.match(line):
                    waiting_for_chapter_title = False
                elif line.startswith("§"):
                    waiting_for_chapter_title = False
                elif line.isupper() and len(line) <= 140:
                    chapter_title = line
                    waiting_for_chapter_title = False
                    continue

            section_match = SECTION_LINE_RE.match(line)
            if section_match:
                flush_section()
                current_section_id = normalize_inline_text(section_match.group(1))
                current_section_heading = normalize_inline_text(section_match.group(2))
                continue

            if current_section_id:
                current_body.append(line)

    flush_section()

    # Keep latest unique section by section id, preserving order by first appearance.
    dedup: Dict[str, ScrapedSection] = {}
    for section in sections:
        dedup[section.section_id] = section
    return list(dedup.values())


def _anacortes_chapter_identity(chapter: Tag) -> Tuple[str, str]:
    chapter_id = normalize_inline_text(chapter.get("id") or "")
    chapter_key = _strip_anacortes_prefix(chapter_id)

    header = chapter.find(["h4", "h3"])
    chapter_title = normalize_inline_text(header.get_text(" ", strip=True) if isinstance(header, Tag) else "")
    if not chapter_title:
        chapter_title = f"Chapter {chapter_key}" if chapter_key else "Chapter"

    if not chapter_key:
        fallback_match = re.search(r"([0-9]+(?:\.[0-9]+)+)", chapter_title)
        chapter_key = fallback_match.group(1) if fallback_match else "UNKNOWN"

    return chapter_key, chapter_title


def _anacortes_section_heading(section: Tag, section_id: str) -> str:
    header = section.find(["h6", "h5", "h4", "h3"])
    heading = normalize_inline_text(header.get_text(" ", strip=True) if isinstance(header, Tag) else "")
    if heading.startswith(section_id):
        heading = normalize_inline_text(heading[len(section_id) :])
    return heading or section_id


def _strip_anacortes_prefix(value: str) -> str:
    if value.startswith("AMC_"):
        return value[4:]
    return value


def _is_burlington_noise(line: str) -> bool:
    if line == "City of Burlington, WA":
        return True
    if BURLINGTON_FOOTER_RE.match(line):
        return True
    if BURLINGTON_HEADER_RE.match(line):
        return True
    if line.startswith("Title ") and "GENERAL PROVISIONS" in line:
        return True
    return False


def _clean_burlington_lines(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        if _is_burlington_noise(line):
            continue
        cleaned.append(line)
    return cleaned


def _chapter_from_section_id(section_id: str) -> str:
    parts = section_id.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return section_id


__all__ = [
    "parse_anacortes_html_snapshot",
    "parse_burlington_pdf_snapshot",
    "_parse_burlington_pages_text",
]
