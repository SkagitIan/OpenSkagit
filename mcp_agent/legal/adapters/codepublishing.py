import re
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

from mcp_agent.legal.utils import make_id, normalize_inline_text, normalize_multiline_text, parse_id

SEARCH_URL = "https://www.codepublishing.com/search/"
ORIGIN = "https://www.codepublishing.com"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OpenSkagitLegal/1.0"
)
DEFAULT_TIMEOUT = (5, 20)
FILE_CONDITIONS = [
    'ext "*.html"',
    'excl "disclaimer*"',
    'excl "*nt.html"',
    'excl "index*"',
    'excl "*_*"',
]
HITS_SUFFIX_RE = re.compile(r"\s*\((\d+)\s+hits?\)\s*$", flags=re.IGNORECASE)
HIT_ANCHOR_RE = re.compile(r"^hit\d+$", flags=re.IGNORECASE)


class UpstreamFetchError(RuntimeError):
    pass


class UpstreamParseError(RuntimeError):
    pass


def search(jurisdiction: Dict[str, object], q: str, limit: int) -> List[Dict[str, object]]:
    session = requests.Session()
    payload = _build_search_payload(jurisdiction, q=q, limit=limit)
    headers = _headers_for_search(jurisdiction)

    try:
        resp = session.post(
            SEARCH_URL,
            data=payload,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise UpstreamFetchError(f"search_request_failed: {exc}") from exc

    if resp.status_code != 200:
        raise UpstreamFetchError(f"search_http_{resp.status_code}")

    try:
        return _parse_search_results(resp.text, jurisdiction, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise UpstreamParseError(f"search_parse_failed: {exc}") from exc


def get(jurisdiction: Dict[str, object], id_value: str) -> Dict[str, object]:
    id_slug, doc_url, section_override = parse_id(id_value)
    expected_slug = str(jurisdiction["slug"])
    if id_slug != expected_slug:
        raise ValueError("id_jurisdiction_mismatch")

    normalized_doc_url = _strip_cachebuster(doc_url)
    session = requests.Session()
    headers = _headers_for_get(jurisdiction)

    try:
        resp = session.get(normalized_doc_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamFetchError(f"get_request_failed: {exc}") from exc

    if resp.status_code != 200:
        raise UpstreamFetchError(f"get_http_{resp.status_code}")

    try:
        return _parse_document(
            html=resp.text,
            jurisdiction=jurisdiction,
            doc_url=normalized_doc_url,
            section_override=section_override,
        )
    except Exception as exc:  # noqa: BLE001
        raise UpstreamParseError(f"get_parse_failed: {exc}") from exc


def _build_search_payload(
    jurisdiction: Dict[str, object], q: str, limit: int
) -> Sequence[Tuple[str, str]]:
    payload: List[Tuple[str, str]] = [
        ("cmd", "search"),
        ("SearchForm", str(jurisdiction["search_form"])),
        ("OrigSearchForm", str(jurisdiction["orig_search_form"])),
        ("index", str(jurisdiction["search_index"])),
        ("autoStopLimit", "5000"),
        ("autoTermWeight", "yes"),
        ("pageSize", str(limit)),
        ("booleanConditions", ""),
        ("maxFiles", "200"),
    ]
    payload.extend(("fileConditions", cond) for cond in FILE_CONDITIONS)
    payload.extend(
        [
            ("request", q),
            ("searchType", "allwords"),
            ("stemming", "on"),
            ("fuzziness", "1"),
            ("userSynonyms", "No"),
            ("sort", "Hits"),
        ]
    )
    return payload


def _headers_for_search(jurisdiction: Dict[str, object]) -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Origin": ORIGIN,
        "Referer": str(jurisdiction["base_url"]),
        "X-Requested-With": "XMLHttpRequest",
    }


def _headers_for_get(jurisdiction: Dict[str, object]) -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain, */*; q=0.01",
        "Referer": str(jurisdiction["base_url"]),
        "X-Requested-With": "XMLHttpRequest",
    }


def _strip_cachebuster(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("_", None)
    cleaned_qs = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=cleaned_qs))


def _normalize_getdoc_url(url: str) -> str:
    cleaned = _strip_cachebuster(url)
    parsed = urlparse(cleaned)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if (qs.get("cmd") or [None])[0] != "getdoc":
        return cleaned

    normalized: List[Tuple[str, str]] = []
    for key in ("cmd", "DocId", "Index", "SearchForm"):
        values = qs.get(key) or []
        if values and values[0]:
            normalized.append((key, values[0]))

    hits_values = qs.get("hits") or []
    if hits_values and hits_values[0]:
        first_hit = hits_values[0].strip().split()[0].split("+")[0].strip()
        if first_hit:
            normalized.append(("HitCount", "1"))
            normalized.append(("hits", f"{first_hit}+"))

    return urlunparse(parsed._replace(query=urlencode(normalized, doseq=True)))


def _parse_search_results(
    html: str, jurisdiction: Dict[str, object], limit: int
) -> List[Dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("p.resultLink a.file")
    hits: List[Dict[str, object]] = []
    for link in links[:limit]:
        href = (link.get("href") or "").strip()
        if not href:
            continue

        absolute_getdoc = _normalize_getdoc_url(urljoin(ORIGIN, href))
        canonical_name = (link.get("name") or "").strip()
        canonical_url = urljoin(ORIGIN, canonical_name) if canonical_name else absolute_getdoc

        raw_label = normalize_inline_text(link.get_text(" ", strip=True))
        hit_count_match = HITS_SUFFIX_RE.search(raw_label)
        heading = HITS_SUFFIX_RE.sub("", raw_label).strip()

        preview_text = _preview_text_for_link(soup, link)
        cite = _derive_cite(heading)

        item: Dict[str, object] = {
            "id": make_id(str(jurisdiction["slug"]), absolute_getdoc),
            "cite": cite,
            "heading": heading,
            "snippet": preview_text,
            "url": canonical_url,
        }
        if hit_count_match:
            raw_count = int(hit_count_match.group(1))
            item["score"] = min(1.0, raw_count / 10.0)
        hits.append(item)

    return hits


def _preview_text_for_link(soup: BeautifulSoup, link: Tag) -> str:
    rel_attr = link.get("rel")
    preview_id: Optional[str] = None
    if isinstance(rel_attr, (list, tuple)) and rel_attr:
        preview_id = str(rel_attr[0]).lstrip("#")
    elif isinstance(rel_attr, str):
        preview_id = rel_attr.lstrip("#")

    if not preview_id:
        return ""

    preview = soup.find(id=preview_id)
    if not preview:
        return ""
    return normalize_inline_text(preview.get_text(" ", strip=True))


def _derive_cite(heading: str) -> Optional[str]:
    if not heading:
        return None
    chapter_match = re.match(r"^(Chapter\s+\d+(?:\.\d+)*)\b", heading, flags=re.IGNORECASE)
    if chapter_match:
        return chapter_match.group(1)
    section_match = re.match(r"^(\d+(?:\.\d+){1,})\b", heading)
    if section_match:
        return section_match.group(1)
    return None


def _parse_document(
    html: str,
    jurisdiction: Dict[str, object],
    doc_url: str,
    section_override: Optional[str],
) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("div", id="mainContent")
    if not main:
        raise UpstreamParseError("main_content_missing")

    sections = [
        tag
        for tag in main.find_all("h3")
        if isinstance(tag, Tag) and "Cite" in (tag.get("class") or [])
    ]

    target = _select_target_section(main, sections, section_override)
    target_section_id = target.get("id") if target else None
    canonical_url = _canonical_doc_url(soup, doc_url, target_section_id)

    if target:
        cite = target_section_id
        text = _extract_section_text(target)
        neighbors = _neighbor_ids(
            sections=sections,
            target=target,
            slug=str(jurisdiction["slug"]),
            doc_url=doc_url,
        )
    else:
        cite = _derive_cite(normalize_inline_text((soup.title.get_text() if soup.title else "")))
        text = normalize_multiline_text(main.get_text("\n", strip=True))
        neighbors = None

    response: Dict[str, object] = {
        "cite": cite,
        "text": text,
        "url": canonical_url,
    }
    if neighbors:
        response["neighbors"] = neighbors
    return response


def _select_target_section(
    main: Tag, sections: List[Tag], section_override: Optional[str]
) -> Optional[Tag]:
    if section_override:
        explicit = main.find("h3", id=section_override)
        if isinstance(explicit, Tag) and "Cite" in (explicit.get("class") or []):
            return explicit

    hit_anchor = main.find("a", attrs={"name": HIT_ANCHOR_RE})
    if isinstance(hit_anchor, Tag):
        container = hit_anchor.find_parent("h3")
        if isinstance(container, Tag) and "Cite" in (container.get("class") or []):
            return container
        previous = hit_anchor.find_previous("h3")
        if isinstance(previous, Tag) and "Cite" in (previous.get("class") or []):
            return previous

    return sections[0] if sections else None


def _extract_section_text(section_header: Tag) -> str:
    lines: List[str] = []
    heading = normalize_inline_text(section_header.get_text(" ", strip=True))
    if heading:
        lines.append(heading)

    for sibling in section_header.next_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name == "h3" and "Cite" in (sibling.get("class") or []):
            break
        text = normalize_inline_text(sibling.get_text(" ", strip=True))
        if text:
            lines.append(text)

    return "\n".join(lines)


def _neighbor_ids(
    sections: List[Tag],
    target: Tag,
    slug: str,
    doc_url: str,
) -> Optional[Dict[str, str]]:
    target_index = -1
    for idx, section in enumerate(sections):
        if section is target:
            target_index = idx
            break

    if target_index < 0:
        return None

    neighbors: Dict[str, str] = {}
    if target_index > 0:
        prev_id = (sections[target_index - 1].get("id") or "").strip()
        if prev_id:
            neighbors["prev"] = make_id(slug, doc_url, section=prev_id)
    if target_index + 1 < len(sections):
        next_id = (sections[target_index + 1].get("id") or "").strip()
        if next_id:
            neighbors["next"] = make_id(slug, doc_url, section=next_id)

    return neighbors or None


def _canonical_doc_url(soup: BeautifulSoup, fallback_url: str, section_id: Optional[str]) -> str:
    base = soup.find("base")
    base_href = ""
    if isinstance(base, Tag):
        base_href = (base.get("href") or "").strip()
    canonical = urljoin(ORIGIN, base_href) if base_href else fallback_url
    if section_id:
        return f"{canonical}#{section_id}"
    return canonical
