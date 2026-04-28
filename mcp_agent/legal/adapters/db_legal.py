import base64
import json
import re
from urllib.parse import parse_qs, urlparse
from typing import Dict, List, Optional, Sequence, Tuple

from django.db.models import OuterRef, Q, QuerySet, Subquery

from legal_code.models import Jurisdiction as DbJurisdiction
from legal_code.models import JurisdictionAlias, LawSection
from mcp_agent.legal.utils import normalize_inline_text, normalize_multiline_text

ID_PREFIX_BY_PUBLISHER = {
    "codepublishing": "cp",
    "municipal_codes": "mc",
    "ecode360": "ec",
    "wa_legislature": "wa",
}

VENDOR_ALIASES_BY_PUBLISHER = {
    "codepublishing": ("codepublishing",),
    "municipal_codes": ("municipal_codes", "municipal.codes"),
    "ecode360": ("ecode360",),
    "wa_legislature": ("wa_legislature",),
}

DB_JURISDICTION_NAME_ALIASES = {
    "sedro_woolley": ("City of Sedro-Woolley", "sedro woolley"),
    "mount_vernon": ("City of Mount Vernon", "mount vernon"),
    "la_conner": ("Town of La Conner", "la conner"),
    "skagit_county": ("Skagit County", "skagit county"),
    "anacortes": ("City of Anacortes", "Anacortes"),
    "burlington": ("City of Burlington", "Burlington"),
    "washington_state": ("State of Washington (Laws and Rules)", "State of Washington (RCW)"),
}

TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+")
NUMERIC_CITE_RE = re.compile(r"\b\d+(?:\.\d+){2,}\b")
WAC_CITE_RE = re.compile(r"\b\d{1,4}(?:-\d{1,4}){1,3}\b")
SECTION_ID_RE = re.compile(r"^\d+(?:\.\d+)+$")
WAC_ID_RE = re.compile(r"^\d{1,4}(?:-\d{1,4}){1,3}$")


class NotFoundError(RuntimeError):
    pass


def search(jurisdiction: Dict[str, object], q: str, limit: int) -> List[Dict[str, object]]:
    query_text = normalize_inline_text(q)
    if not query_text:
        return []

    slug = _jurisdiction_slug(jurisdiction)
    publisher = _jurisdiction_publisher(jurisdiction)
    prefix = ID_PREFIX_BY_PUBLISHER.get(publisher)
    if not prefix:
        raise ValueError("unsupported_jurisdiction")

    sections_qs = _latest_sections_queryset(jurisdiction)
    if not sections_qs.exists():
        return []

    citation_terms = _extract_citation_terms(query_text)
    if citation_terms:
        cite_filter = _citation_filter(citation_terms)
        candidates = list(
            sections_qs.filter(cite_filter)
            .order_by("-scraped_at", "-id")[: max(100, limit * 8)]
        )
        if not candidates:
            # Fail safely for precise cite queries: do not return unrelated sections.
            return []
    else:
        search_filter = _build_search_filter(query_text)
        candidates = list(
            sections_qs.filter(search_filter)
            .order_by("-scraped_at", "-id")[: max(100, limit * 8)]
        )

    hits: List[Dict[str, object]] = []
    query_lower = query_text.lower()
    tokens = _search_tokens(query_text)
    for section in candidates:
        score = _score_section(
            section=section,
            query_lower=query_lower,
            tokens=tokens,
            citation_terms=citation_terms,
        )
        if score <= 0:
            continue

        hits.append(
            {
                "id": _make_id(
                    prefix=prefix,
                    slug=slug,
                    document_key=section.chapter.document.title_number,
                    chapter_key=section.chapter.chapter_number,
                    section_id=section.section_id,
                ),
                "cite": _derive_cite(section),
                "heading": section.heading,
                "snippet": _build_snippet(section.content, query_text),
                "url": section.source_url,
                "score": score,
            }
        )

    hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return hits[:limit]


def get(jurisdiction: Dict[str, object], id_value: str) -> Dict[str, object]:
    slug = _jurisdiction_slug(jurisdiction)
    publisher = _jurisdiction_publisher(jurisdiction)
    expected_prefix = ID_PREFIX_BY_PUBLISHER.get(publisher)
    if not expected_prefix:
        raise ValueError("unsupported_jurisdiction")

    prefix, id_slug, document_key, chapter_key, section_id = _parse_id(id_value)
    if prefix != expected_prefix:
        raise ValueError("id_prefix_mismatch")
    if id_slug != slug:
        raise ValueError("id_jurisdiction_mismatch")

    section = (
        _latest_sections_queryset(jurisdiction)
        .filter(
            chapter__document__title_number=document_key,
            chapter__chapter_number=chapter_key,
            section_id=section_id,
        )
        .order_by("-scraped_at", "-id")
        .first()
    )
    if section is None:
        raise NotFoundError("id_not_found")

    payload: Dict[str, object] = {
        "cite": _derive_cite(section),
        "text": normalize_multiline_text(section.content),
        "url": section.source_url,
    }
    neighbors = _neighbors_for_section(section, prefix=expected_prefix, slug=slug)
    if neighbors:
        payload["neighbors"] = neighbors
    return payload


def _jurisdiction_slug(jurisdiction: Dict[str, object]) -> str:
    slug = normalize_inline_text(str(jurisdiction.get("slug") or "")).lower()
    if not slug:
        raise ValueError("invalid_jurisdiction")
    return slug


def _jurisdiction_publisher(jurisdiction: Dict[str, object]) -> str:
    return normalize_inline_text(str(jurisdiction.get("publisher") or "")).lower()


def _latest_sections_queryset(jurisdiction: Dict[str, object]) -> QuerySet[LawSection]:
    jurisdiction_ids = _resolve_jurisdiction_ids(jurisdiction)
    if not jurisdiction_ids:
        return LawSection.objects.none()

    publisher = _jurisdiction_publisher(jurisdiction)
    vendor_aliases = VENDOR_ALIASES_BY_PUBLISHER.get(publisher, ())
    if not vendor_aliases:
        return LawSection.objects.none()

    latest_id_per_section = LawSection.objects.filter(
        chapter_id=OuterRef("chapter_id"),
        section_id=OuterRef("section_id"),
    ).order_by("-scraped_at", "-id").values("id")[:1]

    return (
        LawSection.objects.select_related(
            "chapter",
            "chapter__document",
            "chapter__document__jurisdiction",
        )
        .filter(
            id=Subquery(latest_id_per_section),
            chapter__document__jurisdiction_id__in=jurisdiction_ids,
            chapter__document__source_vendor__in=vendor_aliases,
        )
    )


def _resolve_jurisdiction_ids(jurisdiction: Dict[str, object]) -> List[int]:
    slug = _jurisdiction_slug(jurisdiction)
    configured_name = normalize_inline_text(str(jurisdiction.get("name") or ""))
    configured_aliases = [
        normalize_inline_text(str(value))
        for value in (jurisdiction.get("aliases") or [])
        if str(value).strip()
    ]

    candidates = {
        configured_name,
        slug.replace("_", " "),
        slug.replace("_", " ").title(),
        *DB_JURISDICTION_NAME_ALIASES.get(slug, ()),
    }
    candidates = {candidate for candidate in candidates if candidate}

    by_name_query = Q()
    for candidate in candidates:
        by_name_query |= Q(name__iexact=candidate)
    ids = set(DbJurisdiction.objects.filter(by_name_query).values_list("id", flat=True))

    alias_values = {slug, *configured_aliases}
    normalized_aliases = {_normalize_alias(value) for value in alias_values if value}
    if normalized_aliases:
        ids.update(
            JurisdictionAlias.objects.filter(alias_normalized__in=normalized_aliases).values_list(
                "jurisdiction_id",
                flat=True,
            )
        )

    return sorted(ids)


def _normalize_alias(value: str) -> str:
    text = normalize_inline_text(value).lower()
    return "_".join(text.split())


def _build_search_filter(query_text: str) -> Q:
    query = (
        Q(section_id__icontains=query_text)
        | Q(heading__icontains=query_text)
        | Q(content__icontains=query_text)
    )
    for token in _search_tokens(query_text):
        query |= (
            Q(section_id__icontains=token)
            | Q(heading__icontains=token)
            | Q(content__icontains=token)
        )
    return query


def _extract_citation_terms(query_text: str) -> List[str]:
    terms = []
    terms.extend(NUMERIC_CITE_RE.findall(query_text))
    terms.extend(WAC_CITE_RE.findall(query_text))

    normalized = []
    seen = set()
    for term in terms:
        clean = normalize_inline_text(term)
        if not clean:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        normalized.append(clean)
    return normalized


def _citation_filter(terms: Sequence[str]) -> Q:
    query = Q()
    for term in terms:
        query |= Q(section_id__iexact=term)
    return query


def _search_tokens(query_text: str) -> List[str]:
    tokens = [token.lower() for token in TOKEN_RE.findall(query_text)]
    return [token for token in tokens if len(token) >= 2]


def _score_section(
    *,
    section: LawSection,
    query_lower: str,
    tokens: Sequence[str],
    citation_terms: Sequence[str],
) -> float:
    section_id = (section.section_id or "").lower()
    heading = (section.heading or "").lower()
    content = (section.content or "").lower()

    if citation_terms:
        normalized_terms = {term.lower() for term in citation_terms}
        if section_id in normalized_terms:
            return 1.0
        return 0.0

    score = 0.0
    if query_lower in section_id:
        score = max(score, 1.0)
    if query_lower in heading:
        score = max(score, 0.9)
    if query_lower in content:
        score = max(score, 0.75)

    if score == 0.0 and tokens:
        token_hits = 0
        for token in tokens:
            if token in section_id or token in heading or token in content:
                token_hits += 1
        if token_hits:
            score = min(0.74, 0.25 + 0.15 * token_hits)

    return round(min(1.0, score), 4)


def _build_snippet(content: str, query_text: str) -> str:
    text = normalize_multiline_text(content)
    if not text:
        return ""

    max_len = 260
    lower_text = text.lower()
    query_lower = query_text.lower()
    idx = lower_text.find(query_lower)
    if idx < 0:
        for token in _search_tokens(query_text):
            idx = lower_text.find(token)
            if idx >= 0:
                break

    if idx < 0:
        return text[:max_len].strip()

    start = max(0, idx - 80)
    end = min(len(text), start + max_len)
    return text[start:end].strip()


def _derive_cite(section: LawSection) -> Optional[str]:
    title_number = normalize_inline_text(section.chapter.document.title_number).upper()
    section_id = normalize_inline_text(section.section_id)
    if not section_id:
        return None

    if title_number in {"RCW", "WAC", "CONSTITUTION", "ETHIC", "RCWDISPOSITION"}:
        return f"{title_number} {section_id}"
    return section_id


def _neighbors_for_section(section: LawSection, *, prefix: str, slug: str) -> Optional[Dict[str, str]]:
    latest_id_per_section = LawSection.objects.filter(
        chapter_id=OuterRef("chapter_id"),
        section_id=OuterRef("section_id"),
    ).order_by("-scraped_at", "-id").values("id")[:1]

    chapter_sections = list(
        LawSection.objects.select_related("chapter", "chapter__document")
        .filter(chapter_id=section.chapter_id, id=Subquery(latest_id_per_section))
        .order_by("section_id", "-scraped_at", "-id")
    )
    if not chapter_sections:
        return None

    idx = next((i for i, item in enumerate(chapter_sections) if item.section_id == section.section_id), -1)
    if idx < 0:
        return None

    payload: Dict[str, str] = {}
    if idx > 0:
        prev_section = chapter_sections[idx - 1]
        payload["prev"] = _make_id(
            prefix=prefix,
            slug=slug,
            document_key=prev_section.chapter.document.title_number,
            chapter_key=prev_section.chapter.chapter_number,
            section_id=prev_section.section_id,
        )
    if idx + 1 < len(chapter_sections):
        next_section = chapter_sections[idx + 1]
        payload["next"] = _make_id(
            prefix=prefix,
            slug=slug,
            document_key=next_section.chapter.document.title_number,
            chapter_key=next_section.chapter.chapter_number,
            section_id=next_section.section_id,
        )
    return payload or None


def _make_id(*, prefix: str, slug: str, document_key: str, chapter_key: str, section_id: str) -> str:
    payload = {
        "c": normalize_inline_text(chapter_key),
        "d": normalize_inline_text(document_key),
        "s": normalize_inline_text(section_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"{prefix}:{slug}:{token}"


def _parse_id(id_value: str) -> Tuple[str, str, str, str, str]:
    parts = id_value.split(":", 2)
    if len(parts) != 3:
        raise ValueError("invalid_id_format")

    prefix = normalize_inline_text(parts[0]).lower()
    slug = normalize_inline_text(parts[1]).lower()
    token = normalize_inline_text(parts[2])
    if not prefix or not slug or not token:
        raise ValueError("invalid_id_format")

    payload = _decode_payload_token(token)
    # Backward compatibility for legacy upstream IDs, e.g. payloads with {"u": "..."}.
    legacy = _parse_legacy_payload(payload)
    if legacy is not None:
        return prefix, slug, legacy[0], legacy[1], legacy[2]

    document_key = normalize_inline_text(str(payload.get("d") or ""))
    chapter_key = normalize_inline_text(str(payload.get("c") or ""))
    section_id = normalize_inline_text(str(payload.get("s") or ""))
    if not document_key or not chapter_key or not section_id:
        raise ValueError("invalid_id_payload")

    return prefix, slug, document_key, chapter_key, section_id


def _decode_payload_token(token: str) -> Dict[str, object]:
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode((token + padding).encode("utf-8"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_id_payload") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid_id_payload")
    return payload


def _parse_legacy_payload(payload: Dict[str, object]) -> Optional[Tuple[str, str, str]]:
    legacy_url = normalize_inline_text(str(payload.get("u") or ""))
    if not legacy_url:
        return None

    section_id = _extract_legacy_section_id(payload, legacy_url)
    if not section_id:
        raise ValueError("legacy_id_ambiguous")

    document_key = "WAC" if WAC_ID_RE.match(section_id) else "ALL"
    chapter_key = _chapter_from_section_id(section_id)
    return document_key, chapter_key, section_id


def _extract_legacy_section_id(payload: Dict[str, object], legacy_url: str) -> str:
    explicit = normalize_inline_text(str(payload.get("s") or ""))
    if _is_section_id(explicit):
        return explicit

    parsed = urlparse(legacy_url)
    fragment = normalize_inline_text(parsed.fragment)
    if _is_section_id(fragment):
        return fragment

    query = parse_qs(parsed.query, keep_blank_values=True)
    hits = normalize_inline_text((query.get("hits") or [""])[0])
    if hits:
        first = hits.split("+", 1)[0].split(" ", 1)[0].strip()
        if _is_section_id(first):
            return first

    if parsed.path:
        last_segment = normalize_inline_text(parsed.path.rstrip("/").split("/")[-1])
        if _is_section_id(last_segment):
            return last_segment

    return ""


def _is_section_id(value: str) -> bool:
    if not value:
        return False
    return bool(SECTION_ID_RE.match(value) or WAC_ID_RE.match(value))


def _chapter_from_section_id(section_id: str) -> str:
    if "." in section_id:
        parts = section_id.split(".")
        if len(parts) >= 2:
            return ".".join(parts[:2])
        return section_id
    if "-" in section_id:
        parts = section_id.split("-")
        if len(parts) >= 2:
            return "-".join(parts[:2])
    return section_id
