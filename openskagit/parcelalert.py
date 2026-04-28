from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from openskagit.context_processors import primary_nav_links
from openskagit.models import (
    MasterParcel,
    ParcelHistory,
    ParcelOwner,
    PropertyRecordAlertSubscription,
    WeeklyBriefingSubscriber,
)

logger = logging.getLogger(__name__)

RECORDER_RESULTS_URL = "https://www.skagitcounty.net/Search/Recording/results.aspx"
ASSESSOR_FILL_PAGE_URL = "https://www.skagitcounty.net/search/property/Webservice.asmx/fillPage"
ASSESSOR_SEARCH_URL = "https://www.skagitcounty.net/search/property/"

MAX_CACHED_RECORDING_DOCUMENTS = 250
PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES = 10
PROPERTY_RECORD_ALERT_UNSUBSCRIBE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365
PROPERTY_RECORD_ALERT_MANAGE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365

HIGH_SIGNAL_DOC_TYPE_KEYWORDS = (
    "quitclaim",
    "deed",
    "lien",
    "release",
    "power of attorney",
    "poa",
)

HIGH_PRIORITY_DOC_TYPE_KEYWORDS = ("quitclaim", "power of attorney", "poa")
SATISFACTION_DOC_TYPE_KEYWORDS = ("satisfaction", "satisfaction of mortgage")
REFINANCE_OR_SALE_SIGNAL_KEYWORDS = (
    "refinance",
    "deed of trust",
    "warranty deed",
    "statutory warranty deed",
    "bargain and sale",
    "reconveyance",
    "purchase and sale",
    "loan payoff",
    "sale",
)


@dataclass(frozen=True)
class PropertyRecordAlertDigestPayload:
    subject: str
    text: str
    html: str
    document_count: int


@dataclass(frozen=True)
class PropertyRecordAlertSignupPayload:
    subject: str
    text: str
    html: str


def _basic_page_context(request, title: str, description: str) -> dict[str, Any]:
    context = {
        "page_title": title,
        "meta_description": description,
        "og_title": title,
        "og_description": description,
        "og_type": "website",
        "og_image": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1765735577/ChatGPT_Image_Dec_14_2025_10_05_37_AM_oprqoo.png",
        "meta_robots": "",
        "twitter_title": title,
        "twitter_description": description,
        "twitter_image": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1765735577/ChatGPT_Image_Dec_14_2025_10_05_37_AM_oprqoo.png",
        "twitter_card": "summary_large_image",
        "canonical_url": None,
        "og_url": None,
        "favicon": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1768253765/logoicon_c_crop_w_480_h_467_x_0_y_0-Picsart-BackgroundRemover_uklqfi.png",
        "apple_touch_icon": "https://res.cloudinary.com/dfz4bhlzs/image/upload/v1768253765/logoicon_c_crop_w_480_h_467_x_0_y_0-Picsart-BackgroundRemover_uklqfi.png",
    }
    context.update(primary_nav_links(request))
    return context


def _load_request_payload(request) -> dict:
    try:
        return json.loads(request.body.decode("utf-8"))
    except (AttributeError, ValueError, UnicodeDecodeError):
        if hasattr(request.POST, "dict"):
            return request.POST.dict()
        return dict(request.POST)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_iso_date(value: str) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _safe_trimmed_text(value: Any, *, max_length: int = 0) -> str:
    text = str(value or "").strip()
    if max_length > 0:
        return text[:max_length]
    return text


def _normalize_parcel_contexts(raw_contexts: Any) -> dict[str, dict[str, str]]:
    contexts_by_parcel: dict[str, dict[str, str]] = {}
    missing_markers = {"owner unavailable", "address unavailable", "-", "n/a", "na", "unknown"}

    if isinstance(raw_contexts, dict):
        context_items = [
            (str(parcel_id or ""), context_payload)
            for parcel_id, context_payload in raw_contexts.items()
        ]
    elif isinstance(raw_contexts, (list, tuple)):
        context_items = []
        for context_payload in raw_contexts:
            if not isinstance(context_payload, dict):
                continue
            context_items.append(
                (
                    str(context_payload.get("parcel_id") or context_payload.get("parcel") or ""),
                    context_payload,
                )
            )
    else:
        context_items = []

    for parcel_value, context_payload in context_items:
        parcel_id = normalize_parcel_id(parcel_value)
        if not parcel_id or not isinstance(context_payload, dict):
            continue

        owner_name = _safe_trimmed_text(
            context_payload.get("owner_name"),
            max_length=255,
        )
        situs_address = _safe_trimmed_text(
            context_payload.get("situs_address"),
            max_length=300,
        )
        if owner_name.lower() in missing_markers:
            owner_name = ""
        if situs_address.lower() in missing_markers:
            situs_address = ""

        contexts_by_parcel[parcel_id] = {
            "owner_name": owner_name,
            "situs_address": situs_address,
        }
    return contexts_by_parcel


def _normalize_monitored_names(
    raw_names: Any,
    *,
    baseline_owner_name: str = "",
    max_names: int = 15,
) -> list[str]:
    candidates: list[str] = []
    if isinstance(raw_names, str):
        candidates.extend(re.split(r"[\n,;]+", raw_names))
    elif isinstance(raw_names, (list, tuple, set)):
        for raw in raw_names:
            if isinstance(raw, str):
                candidates.extend(re.split(r"[\n,;]+", raw))
            else:
                candidates.append(str(raw or ""))
    elif raw_names is not None:
        candidates.append(str(raw_names))

    if baseline_owner_name:
        candidates.append(str(baseline_owner_name))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        cleaned = _clean_text(item)
        if not cleaned:
            continue
        key = re.sub(r"\s+", " ", cleaned).strip().lower()
        if key in {"owner unavailable", "unknown", "-", "n/a", "na"}:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned[:255])
        if len(deduped) >= max_names:
            break
    return deduped


def _normalize_match_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _split_terms(value: str) -> list[str]:
    return [term for term in _normalize_match_text(value).split() if len(term) >= 3]

def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _sync_weekly_briefing_opt_in(email: str, *, opted_in: bool) -> dict[str, bool]:
    if not opted_in:
        return {
            "weekly_briefing_opt_in": False,
            "weekly_briefing_subscribed": False,
            "weekly_briefing_created": False,
        }

    normalized_email = normalize_email(email)
    if not normalized_email:
        return {
            "weekly_briefing_opt_in": True,
            "weekly_briefing_subscribed": False,
            "weekly_briefing_created": False,
        }

    try:
        _subscriber, created = WeeklyBriefingSubscriber.objects.get_or_create(
            email=normalized_email
        )
        return {
            "weekly_briefing_opt_in": True,
            "weekly_briefing_subscribed": True,
            "weekly_briefing_created": bool(created),
        }
    except Exception:
        logger.exception(
            "property_record_alert.weekly_briefing_subscribe_failed",
            extra={"email": normalized_email},
        )
        return {
            "weekly_briefing_opt_in": True,
            "weekly_briefing_subscribed": False,
            "weekly_briefing_created": False,
        }


def normalize_parcel_id(value: str) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    if not raw:
        return ""
    if raw.startswith("P"):
        return raw
    digits_only = re.sub(r"\D", "", raw)
    if digits_only:
        return f"P{digits_only}"
    return raw


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _normalize_document_type(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def is_high_signal_document_type(document_type: str) -> bool:
    normalized = _normalize_document_type(document_type)
    if not normalized:
        return False
    if "power of attorney" in normalized:
        return True
    if normalized == "poa" or "poa" in normalized.split():
        return True
    return any(
        keyword in normalized
        for keyword in HIGH_SIGNAL_DOC_TYPE_KEYWORDS
        if keyword not in {"power of attorney", "poa"}
    )


def _soundex(value: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", str(value or "")).upper()
    if not letters:
        return ""

    first = letters[0]
    mapping = {
        **{c: "1" for c in "BFPV"},
        **{c: "2" for c in "CGJKQSXZ"},
        **{c: "3" for c in "DT"},
        "L": "4",
        **{c: "5" for c in "MN"},
        "R": "6",
    }
    code_chars = [first]
    last_digit = mapping.get(first, "")
    for char in letters[1:]:
        digit = mapping.get(char, "")
        if not digit:
            last_digit = ""
            continue
        if digit == last_digit:
            continue
        code_chars.append(digit)
        last_digit = digit
        if len(code_chars) == 4:
            break
    while len(code_chars) < 4:
        code_chars.append("0")
    return "".join(code_chars[:4])


def _levenshtein_distance(a: str, b: str, *, max_distance: int = 2) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1

    prev = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        cur = [i]
        row_min = i
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            cur_val = min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + cost,
            )
            cur.append(cur_val)
            if cur_val < row_min:
                row_min = cur_val
        if row_min > max_distance:
            return max_distance + 1
        prev = cur
    return prev[-1]


def _is_high_priority_document_type(document_type: str) -> bool:
    normalized = _normalize_document_type(document_type)
    if not normalized:
        return False
    if "quitclaim" in normalized:
        return True
    if "power of attorney" in normalized:
        return True
    if normalized == "poa" or " poa " in f" {normalized} ":
        return True
    return False


def _is_satisfaction_document_type(document_type: str) -> bool:
    normalized = _normalize_document_type(document_type)
    return any(keyword in normalized for keyword in SATISFACTION_DOC_TYPE_KEYWORDS)


def _has_refinance_or_sale_signal(recent_documents: Sequence[dict[str, Any]]) -> bool:
    for document in recent_documents[:12]:
        combined = _normalize_match_text(
            " ".join(
                [
                    str(document.get("document_type") or ""),
                    str(document.get("comment") or ""),
                    str(document.get("legal") or ""),
                ]
            )
        )
        if not combined:
            continue
        if any(keyword in combined for keyword in REFINANCE_OR_SALE_SIGNAL_KEYWORDS):
            return True
    return False


def _extract_name_terms(value: str) -> list[str]:
    return [token for token in _split_terms(value) if len(token) >= 2]


def _name_match_signals(monitored_names: Sequence[str], party_values: Sequence[str]) -> list[str]:
    signals: set[str] = set()
    normalized_parties = [_normalize_match_text(value) for value in party_values if _normalize_match_text(value)]
    party_tokens: list[str] = []
    for party in normalized_parties:
        party_tokens.extend([token for token in party.split() if len(token) >= 2])

    for monitored in monitored_names:
        normalized_monitored = _normalize_match_text(monitored)
        if not normalized_monitored:
            continue
        monitored_tokens = [token for token in normalized_monitored.split() if len(token) >= 2]
        monitored_last = monitored_tokens[-1] if monitored_tokens else ""
        monitored_last_soundex = _soundex(monitored_last)

        for party in normalized_parties:
            if normalized_monitored in party or party in normalized_monitored:
                signals.add("exact_name")

        for token in monitored_tokens:
            if len(token) < 5:
                continue
            for party_token in party_tokens:
                if len(party_token) < 5:
                    continue
                if _levenshtein_distance(token, party_token, max_distance=2) <= 2:
                    signals.add("fuzzy_name")
                    break

        if monitored_last_soundex:
            for party_token in party_tokens:
                if _soundex(party_token) and _soundex(party_token) == monitored_last_soundex:
                    signals.add("phonetic_name")
                    break

    return sorted(signals)


def _watch_terms_from_subscription(subscription: PropertyRecordAlertSubscription) -> dict[str, Any]:
    monitored_names = _normalize_monitored_names(
        getattr(subscription, "monitored_names", []),
        baseline_owner_name=subscription.baseline_owner_name,
    )
    address_terms = _split_terms(subscription.baseline_situs_address or "")
    legal_terms = _split_terms(subscription.baseline_legal_fragment or "")
    return {
        "parcel_id": normalize_parcel_id(subscription.parcel_id),
        "monitored_names": monitored_names,
        "address_terms": address_terms,
        "legal_terms": legal_terms,
    }


def evaluate_document_risk(
    *,
    subscription: PropertyRecordAlertSubscription,
    document: dict[str, Any],
    recent_documents: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    signals: list[str] = []

    document_type = str(document.get("document_type") or "")
    normalized_doc_type = _normalize_document_type(document_type)
    is_high_priority = _is_high_priority_document_type(document_type)

    if is_high_priority:
        score += 70
        reasons.append("High-priority document type (Quitclaim/POA).")
    elif "deed" in normalized_doc_type:
        score += 30
        reasons.append("Deed-related document.")
    elif "lien" in normalized_doc_type or "release" in normalized_doc_type:
        score += 20
        reasons.append("Lien/release document.")

    if _is_satisfaction_document_type(document_type):
        score += 40
        reasons.append("Satisfaction-related document.")
        current_recording_number = _clean_text(document.get("recording_number"))
        context_documents = [
            item
            for item in recent_documents
            if _clean_text(item.get("recording_number")) != current_recording_number
        ]
        if not _has_refinance_or_sale_signal(context_documents):
            score += 25
            is_high_priority = True
            reasons.append("No nearby refinance/sale signal; promoted to high-risk.")
        else:
            reasons.append("Nearby refinance/sale signal found; not promoted.")

    watch_terms = _watch_terms_from_subscription(subscription)
    party_values = [
        str(document.get("grantor") or ""),
        str(document.get("grantee") or ""),
        str(document.get("filer") or ""),
    ]
    name_signals = _name_match_signals(watch_terms["monitored_names"], party_values)
    if "exact_name" in name_signals:
        score += 25
        signals.append("exact_name")
        reasons.append("Exact monitored name match.")
    if "fuzzy_name" in name_signals:
        score += 18
        signals.append("fuzzy_name")
        reasons.append("Near-match name (Levenshtein <= 2).")
    if "phonetic_name" in name_signals:
        score += 15
        signals.append("phonetic_name")
        reasons.append("Phonetic surname match (Soundex).")

    doc_parcel_id = normalize_parcel_id(document.get("parcel_id") or "")
    if doc_parcel_id and doc_parcel_id == watch_terms["parcel_id"]:
        score += 8
        signals.append("parcel_match")

    combined_text = _normalize_match_text(
        " ".join(
            [
                str(document.get("comment") or ""),
                str(document.get("legal") or ""),
                " ".join(party_values),
            ]
        )
    )
    if watch_terms["address_terms"] and any(term in combined_text for term in watch_terms["address_terms"]):
        score += 8
        signals.append("address_term")
        reasons.append("Address watch-term match.")
    if watch_terms["legal_terms"] and any(term in combined_text for term in watch_terms["legal_terms"]):
        score += 8
        signals.append("legal_term")
        reasons.append("Legal-fragment watch-term match.")

    score = max(0, min(score, 100))
    if score >= 80:
        risk_level = "high"
    elif score >= 60:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "match_signals": sorted(set(signals)),
        "is_high_priority": is_high_priority,
        "triggered": is_high_priority or score >= 60,
    }


def should_trigger_document_alert(risk_payload: dict[str, Any]) -> bool:
    return bool(risk_payload.get("is_high_priority") or (risk_payload.get("risk_score") or 0) >= 60)


def _parse_date(value: str) -> Optional[dt.date]:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _recorded_date_as_iso(value: Any) -> str:
    if isinstance(value, dt.date):
        return value.isoformat()
    parsed = _parse_date(str(value or ""))
    return parsed.isoformat() if parsed else ""


def parse_recording_results_html(
    html_text: str,
    *,
    source_url: str,
    parcel_id: str,
    fetched_at: Optional[dt.datetime] = None,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    table = soup.find("table", class_=lambda value: value and "resultTable" in value)
    if not table:
        return []

    body = table.find("tbody") or table
    normalized_parcel_id = normalize_parcel_id(parcel_id)
    seen_numbers: set[str] = set()
    documents: list[dict[str, Any]] = []
    fetched_timestamp = (fetched_at or timezone.now()).isoformat()

    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 10:
            continue

        details_cell = cells[3]
        detail_lines = [_clean_text(item) for item in details_cell.stripped_strings]
        recording_number = detail_lines[0] if len(detail_lines) >= 1 else ""
        recorded_date = _parse_date(detail_lines[1]) if len(detail_lines) >= 2 else None
        document_type = detail_lines[2] if len(detail_lines) >= 3 else ""

        if not recording_number:
            continue
        if recording_number in seen_numbers:
            continue
        seen_numbers.add(recording_number)

        parcel_lines = [_clean_text(item) for item in cells[9].stripped_strings if _clean_text(item)]
        parcel_line = ""
        xref_line = ""
        for line in parcel_lines:
            if not parcel_line and normalize_parcel_id(line).startswith("P"):
                parcel_line = normalize_parcel_id(line)
                continue
            if not xref_line:
                xref_line = line

        document_anchor = cells[2].find("a", href=True)
        document_url = (
            urljoin(source_url, document_anchor.get("href", "").strip())
            if document_anchor
            else ""
        )

        documents.append(
            {
                "recording_number": recording_number,
                "recorded_date": recorded_date.isoformat() if recorded_date else "",
                "document_type": document_type,
                "grantor": _clean_text(cells[4].get_text(" ", strip=True)),
                "grantee": _clean_text(cells[5].get_text(" ", strip=True)),
                "filer": _clean_text(cells[6].get_text(" ", strip=True)),
                "comment": _clean_text(cells[7].get_text(" ", strip=True)),
                "legal": _clean_text(cells[8].get_text(" ", strip=True)),
                "parcel_id": parcel_line or normalized_parcel_id,
                "xref_id": xref_line,
                "document_url": document_url,
                "source_url": source_url,
                "fetched_at": fetched_timestamp,
            }
        )

    return documents


def fetch_recording_documents(parcel_id: str, *, timeout: int = 30) -> list[dict[str, Any]]:
    normalized_parcel_id = normalize_parcel_id(parcel_id)
    source_url = build_recording_results_url(normalized_parcel_id)
    response = requests.get(
        RECORDER_RESULTS_URL,
        params={"PA": normalized_parcel_id, "SC": "DateRecorded", "SO": "DESC"},
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (OpenSkagit property record alert)"},
    )
    response.raise_for_status()
    return parse_recording_results_html(
        response.text,
        source_url=source_url,
        parcel_id=normalized_parcel_id,
    )


def build_recording_results_url(parcel_id: str) -> str:
    normalized_parcel_id = normalize_parcel_id(parcel_id)
    params = {"PA": normalized_parcel_id, "SC": "DateRecorded", "SO": "DESC"}
    return f"{RECORDER_RESULTS_URL}?{urlencode(params)}"


def _recording_sort_key(document: dict[str, Any]) -> tuple[dt.date, str]:
    recorded_date = _parse_date(str(document.get("recorded_date") or "")) or dt.date.min
    recording_number = str(document.get("recording_number") or "")
    return recorded_date, recording_number


def merge_recording_documents(
    current_documents: Sequence[dict[str, Any]],
    cached_documents: Sequence[dict[str, Any]],
    *,
    max_items: int = MAX_CACHED_RECORDING_DOCUMENTS,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for document in list(current_documents) + list(cached_documents):
        number = _clean_text(document.get("recording_number"))
        if not number or number in seen_numbers:
            continue
        seen_numbers.add(number)
        normalized = dict(document)
        normalized["recording_number"] = number
        normalized["recorded_date"] = _recorded_date_as_iso(document.get("recorded_date"))
        merged.append(normalized)

    merged.sort(key=_recording_sort_key, reverse=True)
    return merged[: max(1, int(max_items))]


def _collect_documents_until_anchor(
    documents: Sequence[dict[str, Any]],
    anchor_recording_number: str,
) -> tuple[list[dict[str, Any]], bool]:
    anchor = _clean_text(anchor_recording_number)
    if not anchor:
        return [], False

    collected: list[dict[str, Any]] = []
    for document in documents:
        number = _clean_text(document.get("recording_number"))
        if number == anchor:
            return collected, True
        collected.append(document)
    return collected, False


def compute_unsent_documents(
    *,
    merged_documents: Sequence[dict[str, Any]],
    current_documents: Sequence[dict[str, Any]],
    anchor_recording_number: str,
    previous_latest_recording_number: str = "",
) -> list[dict[str, Any]]:
    anchor = _clean_text(anchor_recording_number)
    if not anchor:
        # No cursor means no safe baseline; do not emit historical alerts.
        return []

    primary_docs, primary_found = _collect_documents_until_anchor(
        merged_documents,
        anchor,
    )
    if primary_found:
        return primary_docs

    previous_latest = _clean_text(previous_latest_recording_number)
    if previous_latest:
        fallback_docs, fallback_found = _collect_documents_until_anchor(
            current_documents,
            previous_latest,
        )
        if fallback_found:
            return fallback_docs

    return []


def _assessor_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (OpenSkagit property record alert)",
        "Referer": ASSESSOR_SEARCH_URL,
        "Origin": "https://www.skagitcounty.net",
    }


def _extract_assessor_block_lines(soup: BeautifulSoup, header_text: str) -> list[str]:
    header_node = soup.find(string=lambda value: value and header_text in value)
    if not header_node:
        return []
    table = header_node.find_parent("table")
    if not table:
        return []

    lines: list[str] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        text = _clean_text(" ".join(cell.get_text(" ", strip=True) for cell in cells))
        if not text:
            continue
        if header_text.lower() in text.lower():
            continue
        lines.append(text)
    return lines


def fetch_assessor_baseline_live(parcel_id: str, *, timeout: int = 20) -> dict[str, str]:
    normalized_parcel_id = normalize_parcel_id(parcel_id)
    session = requests.Session()
    session.get(ASSESSOR_SEARCH_URL, timeout=timeout)
    session.cookies.clear()
    session.cookies.set(
        "prophistory",
        f"{normalized_parcel_id},",
        domain="www.skagitcounty.net",
        path="/",
    )

    headers = _assessor_headers()
    nav_payload = "{ 'sValue': '" + normalized_parcel_id + ",','ResultType': 'nav' }"
    session.post(ASSESSOR_FILL_PAGE_URL, data=nav_payload, headers=headers, timeout=timeout)

    details_payload = "{ 'sValue': '" + normalized_parcel_id + "','ResultType': 'Details' }"
    details_response = session.post(
        ASSESSOR_FILL_PAGE_URL,
        data=details_payload,
        headers=headers,
        timeout=timeout,
    )
    details_response.raise_for_status()

    try:
        details_raw = details_response.json().get("d", "")
    except ValueError:
        details_raw = details_response.text
    details_html = html.unescape(details_raw)
    soup = BeautifulSoup(details_html, "html.parser")

    owner_lines = _extract_assessor_block_lines(soup, "Owner Information")
    owner_name = owner_lines[0] if owner_lines else ""

    situs_lines = _extract_assessor_block_lines(soup, "Site Address")
    filtered_situs_lines = [
        line
        for line in situs_lines
        if "Zip Code Lookup" not in line
        and "Site Address Information" not in line
        and "Jurisdiction, State" not in line
    ]
    situs_address = filtered_situs_lines[0] if filtered_situs_lines else ""

    return {
        "owner_name": owner_name,
        "situs_address": situs_address,
        "source": "live",
    }


def fetch_assessor_baseline_fallback(parcel_id: str) -> dict[str, str]:
    normalized_parcel_id = normalize_parcel_id(parcel_id)
    parcel = MasterParcel.objects.filter(parcel_number=normalized_parcel_id).first()
    owner = ParcelOwner.objects.filter(parcel_id=normalized_parcel_id).first()
    return {
        "owner_name": _clean_text(getattr(owner, "owner_name", "")),
        "situs_address": _clean_text(getattr(parcel, "situs_address", "")),
        "source": "db",
    }


def resolve_assessor_baseline(
    parcel_id: str,
    *,
    timeout: int = 20,
    prefer_live: bool = True,
) -> dict[str, str]:
    fallback_values = fetch_assessor_baseline_fallback(parcel_id)
    fallback_owner_name = _clean_text(fallback_values.get("owner_name"))
    fallback_situs_address = _clean_text(fallback_values.get("situs_address"))

    # Fast path for interactive UI preview requests: prefer local data when complete.
    if not prefer_live and fallback_owner_name and fallback_situs_address:
        return {
            "owner_name": fallback_owner_name,
            "situs_address": fallback_situs_address,
            "source": fallback_values.get("source", "db"),
        }

    live_values: dict[str, str] = {}
    try:
        live_values = fetch_assessor_baseline_live(parcel_id, timeout=timeout)
    except Exception:
        logger.warning(
            "property_record_alert.assessor_live_failed",
            extra={"parcel_id": normalize_parcel_id(parcel_id)},
            exc_info=True,
        )

    owner_name = _clean_text(live_values.get("owner_name")) or fallback_owner_name
    situs_address = _clean_text(live_values.get("situs_address")) or fallback_situs_address
    source = "live" if live_values else fallback_values.get("source", "db")

    return {
        "owner_name": owner_name,
        "situs_address": situs_address,
        "source": source,
    }


def build_subscription_unsubscribe_url(subscription: PropertyRecordAlertSubscription) -> str:
    token = subscription.unsubscribe_token()
    return (
        f"{settings.SITE_URL.rstrip('/')}"
        f"{reverse('property-record-alert-unsubscribe', args=[token])}"
    )


def build_subscription_manage_url(subscription: PropertyRecordAlertSubscription) -> str:
    token = subscription.manage_token()
    return (
        f"{settings.SITE_URL.rstrip('/')}"
        f"{reverse('property-record-alert-manage', args=[token])}"
    )


def build_subscription_delete_url(subscription: PropertyRecordAlertSubscription) -> str:
    token = subscription.manage_token()
    return (
        f"{settings.SITE_URL.rstrip('/')}"
        f"{reverse('property-record-alert-delete', args=[token])}"
    )


def serialize_subscription(subscription: PropertyRecordAlertSubscription) -> dict[str, Any]:
    return {
        "email": subscription.email,
        "parcel_id": subscription.parcel_id,
        "baseline_owner_name": subscription.baseline_owner_name,
        "baseline_situs_address": subscription.baseline_situs_address,
        "baseline_legal_fragment": subscription.baseline_legal_fragment,
        "monitored_names": _normalize_monitored_names(
            getattr(subscription, "monitored_names", []),
            baseline_owner_name=subscription.baseline_owner_name,
        ),
        "baseline_recording_number": subscription.baseline_recording_number,
        "baseline_recorded_date": (
            subscription.baseline_recorded_date.isoformat()
            if subscription.baseline_recorded_date
            else None
        ),
        "last_notified_recording_number": subscription.last_notified_recording_number,
        "is_active": subscription.is_active,
        "last_checked_at": subscription.last_checked_at.isoformat() if subscription.last_checked_at else None,
        "last_alert_sent_at": (
            subscription.last_alert_sent_at.isoformat() if subscription.last_alert_sent_at else None
        ),
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
        "manage_url": build_subscription_manage_url(subscription),
        "delete_url": build_subscription_delete_url(subscription),
        "unsubscribe_url": build_subscription_unsubscribe_url(subscription),
    }


def build_property_record_alert_digest_payload(
    *,
    email: str,
    parcel_alerts: Sequence[dict[str, Any]],
) -> PropertyRecordAlertDigestPayload:
    document_count = sum(len(alert.get("documents", [])) for alert in parcel_alerts)
    if document_count == 1:
        subject = "OpenSkagit parcel record alert: 1 new recorded document"
    else:
        subject = f"OpenSkagit parcel record alert: {document_count} new recorded documents"

    context = {
        "recipient_email": normalize_email(email),
        "parcel_alerts": list(parcel_alerts),
        "document_count": document_count,
        "generated_at": timezone.now(),
        "site_url": settings.SITE_URL.rstrip("/"),
    }
    text = render_to_string("openskagit/emails/property_record_alert.txt", context)
    html_body = render_to_string("openskagit/emails/property_record_alert.html", context)
    return PropertyRecordAlertDigestPayload(
        subject=subject,
        text=text,
        html=html_body,
        document_count=document_count,
    )


def build_property_record_alert_signup_payload(
    *,
    email: str,
    parcel_subscriptions: Sequence[dict[str, Any]],
) -> PropertyRecordAlertSignupPayload:
    subject = "OpenSkagit parcel alert signup confirmed"
    context = {
        "recipient_email": normalize_email(email),
        "parcel_subscriptions": list(parcel_subscriptions),
        "generated_at": timezone.now(),
        "site_url": settings.SITE_URL.rstrip("/"),
    }
    text = render_to_string("openskagit/emails/property_record_alert_signup_confirmation.txt", context)
    html_body = render_to_string("openskagit/emails/property_record_alert_signup_confirmation.html", context)
    return PropertyRecordAlertSignupPayload(
        subject=subject,
        text=text,
        html=html_body,
    )


def send_property_record_alert_signup_confirmation(
    *,
    email: str,
    parcel_subscriptions: Sequence[dict[str, Any]],
    from_email: Optional[str] = None,
) -> int:
    recipient = normalize_email(email)
    if not recipient:
        return 0

    subscription_sections = list(parcel_subscriptions)
    if not subscription_sections:
        return 0

    payload = build_property_record_alert_signup_payload(
        email=recipient,
        parcel_subscriptions=subscription_sections,
    )
    headers = {"Auto-Submitted": "auto-generated"}
    first_delete_url = str(subscription_sections[0].get("delete_url") or "").strip()
    if first_delete_url:
        headers["List-Unsubscribe"] = f"<{first_delete_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message = EmailMultiAlternatives(
        subject=payload.subject,
        body=payload.text,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        headers=headers,
    )
    message.attach_alternative(payload.html, "text/html")
    message.send()
    return 1


def send_property_record_alert_digest(
    *,
    email: str,
    parcel_alerts: Sequence[dict[str, Any]],
    from_email: Optional[str] = None,
) -> int:
    recipient = normalize_email(email)
    if not recipient:
        return 0

    payload = build_property_record_alert_digest_payload(
        email=recipient,
        parcel_alerts=parcel_alerts,
    )
    if payload.document_count <= 0:
        return 0

    headers = {"Auto-Submitted": "auto-generated"}
    alert_sections = list(parcel_alerts)
    first_delete_url = str(alert_sections[0].get("delete_url") or "").strip() if alert_sections else ""
    if first_delete_url:
        headers["List-Unsubscribe"] = f"<{first_delete_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    message = EmailMultiAlternatives(
        subject=payload.subject,
        body=payload.text,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        headers=headers,
    )
    message.attach_alternative(payload.html, "text/html")
    message.send()
    return 1


def _update_property_record_alert_subscription(
    *,
    subscription: PropertyRecordAlertSubscription,
    email_raw: str,
    is_active: bool,
    monitored_names_raw: Any = None,
) -> dict[str, str]:
    details: dict[str, str] = {}

    normalized_email = normalize_email(email_raw)
    if not normalized_email:
        details["email"] = "Email is required."
    else:
        try:
            validate_email(normalized_email)
        except ValidationError:
            details["email"] = "Please enter a valid email address."

    if normalized_email and normalized_email != subscription.email:
        duplicate_exists = PropertyRecordAlertSubscription.objects.filter(
            email=normalized_email,
            parcel_id=subscription.parcel_id,
        ).exclude(pk=subscription.pk).exists()
        if duplicate_exists:
            details["email"] = (
                f"{normalized_email} already has an alert for parcel {subscription.parcel_id}."
            )

    if normalized_email and is_active:
        active_count = PropertyRecordAlertSubscription.objects.filter(
            email=normalized_email,
            is_active=True,
        ).exclude(pk=subscription.pk).count()
        if active_count >= PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES:
            details["email"] = (
                f"You can track up to {PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES} parcels per email."
            )

    monitored_source = monitored_names_raw
    if monitored_source is None:
        monitored_source = getattr(subscription, "monitored_names", [])
    monitored_names = _normalize_monitored_names(
        monitored_source,
        baseline_owner_name=subscription.baseline_owner_name,
    )
    if not monitored_names and subscription.baseline_owner_name:
        monitored_names = [subscription.baseline_owner_name]

    if details:
        return details

    changed_fields: list[str] = []
    if subscription.email != normalized_email:
        subscription.email = normalized_email
        changed_fields.append("email")
    if subscription.is_active != is_active:
        subscription.is_active = is_active
        changed_fields.append("is_active")
    if monitored_names != list(getattr(subscription, "monitored_names", []) or []):
        subscription.monitored_names = monitored_names
        changed_fields.append("monitored_names")

    subscription.last_checked_at = timezone.now()
    changed_fields.append("last_checked_at")
    subscription.save(update_fields=changed_fields + ["updated_at"])
    return {}


def _refresh_parcel_history_recording_cache(
    *,
    parcel_id: str,
    current_documents: Sequence[dict[str, Any]],
) -> None:
    if not current_documents:
        return

    history, _created = ParcelHistory.objects.get_or_create(
        parcel_number=parcel_id,
        defaults={"rows": [], "taxes": {}},
    )
    cached_documents = history.recording_documents if isinstance(history.recording_documents, list) else []
    merged_documents = merge_recording_documents(
        current_documents,
        cached_documents,
    )
    latest_number = str(current_documents[0].get("recording_number") or "").strip()
    latest_recorded_date = _as_iso_date(current_documents[0].get("recorded_date") or "")

    history.recording_documents = merged_documents
    history.recording_latest_number = latest_number
    history.recording_latest_recorded_date = latest_recorded_date
    history.recording_checked_at = timezone.now()
    history.recording_last_error = ""
    history.save(
        update_fields=[
            "recording_documents",
            "recording_latest_number",
            "recording_latest_recorded_date",
            "recording_checked_at",
            "recording_last_error",
            "scraped_at",
        ]
    )


@require_GET
def property_record_alert_page(request):
    canonical_url = request.build_absolute_uri(request.path)
    context = _basic_page_context(
        request,
        "Skagit County Parcel Alerts | Recorded Document Email Notifications | OpenSkagit",
        (
            "Track Skagit County parcels and get nightly email alerts when new high-signal recorded documents "
            "appear, including deeds, liens, releases, and powers of attorney."
        ),
    )
    context.update(
        {
            "canonical_url": canonical_url,
            "og_url": canonical_url,
            "og_title": "Skagit County Parcel Alerts | OpenSkagit",
            "og_description": (
                "Free parcel monitoring for recorded document index updates in Skagit County."
            ),
            "twitter_title": "Skagit County Parcel Alerts | OpenSkagit",
            "twitter_description": (
                "Free parcel monitoring for recorded document index updates in Skagit County."
            ),
            "og_image": (
                "https://res.cloudinary.com/dfz4bhlzs/image/upload/"
                "c_fill,g_auto,w_1200,h_630,f_auto,q_auto/"
                "v1774365875/Gemini_Generated_Image_i5qhsti5qhsti5qh_gvrrus.png"
            ),
            "twitter_image": (
                "https://res.cloudinary.com/dfz4bhlzs/image/upload/"
                "c_fill,g_auto,w_1200,h_630,f_auto,q_auto/"
                "v1774365875/Gemini_Generated_Image_i5qhsti5qhsti5qh_gvrrus.png"
            ),
            "meta_robots": "index,follow,max-snippet:-1,max-image-preview:large,max-video-preview:-1",
            "max_active_watches": PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES,
        }
    )
    return render(request, "openskagit/property_record_alert.html", context)


@require_POST
def property_record_alert_subscribe(request):
    payload = _load_request_payload(request)
    email_raw = str(payload.get("email") or "").strip()
    parcel_raw = str(payload.get("parcel_id") or payload.get("parcel") or "").strip()
    raw_parcel_ids = payload.get("parcel_ids")
    monitored_names_raw = payload.get("monitored_names")
    subscribe_weekly_briefing = _is_truthy(payload.get("subscribe_weekly_briefing"))
    parcel_contexts = _normalize_parcel_contexts(payload.get("parcel_contexts"))

    details: dict[str, str] = {}
    if not email_raw:
        details["email"] = "Email is required."
    else:
        try:
            validate_email(email_raw)
        except ValidationError:
            details["email"] = "Please enter a valid email address."

    candidate_parcel_values: list[str] = []
    if isinstance(raw_parcel_ids, (list, tuple)):
        candidate_parcel_values.extend([str(value or "").strip() for value in raw_parcel_ids])
    elif isinstance(raw_parcel_ids, str):
        candidate_parcel_values.extend([part.strip() for part in raw_parcel_ids.split(",")])
    if parcel_raw:
        candidate_parcel_values.append(parcel_raw)

    normalized_parcel_ids: list[str] = []
    seen_parcel_ids: set[str] = set()
    for candidate in candidate_parcel_values:
        normalized = normalize_parcel_id(candidate)
        if not normalized or normalized in seen_parcel_ids:
            continue
        seen_parcel_ids.add(normalized)
        normalized_parcel_ids.append(normalized)

    if not normalized_parcel_ids:
        details["parcel_id"] = "Select at least one parcel."

    accept_terms = _is_truthy(payload.get("accept_terms"))
    if not accept_terms:
        details["accept_terms"] = "You must accept the alert terms before submitting."

    if details:
        logger.warning(
            "property_record_alert.subscribe_invalid_request",
            extra={
                "email": normalize_email(email_raw),
                "requested_parcel_count": len(candidate_parcel_values),
                "normalized_parcel_count": len(normalized_parcel_ids),
                "detail_keys": sorted(details.keys()),
            },
        )
        return JsonResponse(
            {
                "error": "Invalid request.",
                "details": details,
            },
            status=400,
        )

    parcels = MasterParcel.objects.filter(parcel_number__in=normalized_parcel_ids)
    parcels_by_number = {parcel.parcel_number: parcel for parcel in parcels}
    missing_parcels = [parcel_id for parcel_id in normalized_parcel_ids if parcel_id not in parcels_by_number]
    if missing_parcels:
        logger.warning(
            "property_record_alert.subscribe_parcel_not_found",
            extra={
                "email": normalize_email(email_raw),
                "requested_parcel_count": len(normalized_parcel_ids),
                "missing_parcel_count": len(missing_parcels),
                "missing_parcel_sample": missing_parcels[:3],
            },
        )
        sample_missing = ", ".join(missing_parcels[:3])
        if len(missing_parcels) > 3:
            sample_missing = f"{sample_missing}, +{len(missing_parcels) - 3} more"
        return JsonResponse(
            {
                "error": "Parcel not found.",
                "details": {
                    "parcel_id": (
                        "We couldn't find one or more parcels in our records: "
                        f"{sample_missing}."
                    )
                },
            },
            status=400,
        )

    normalized_email = normalize_email(email_raw)
    existing_subscriptions = PropertyRecordAlertSubscription.objects.filter(
        email=normalized_email,
        parcel_id__in=normalized_parcel_ids,
    ).select_related("parcel")
    existing_by_parcel = {subscription.parcel_id: subscription for subscription in existing_subscriptions}

    if len(normalized_parcel_ids) == 1:
        parcel_id = normalized_parcel_ids[0]
        existing = existing_by_parcel.get(parcel_id)
        if existing and existing.is_active:
            serialized = serialize_subscription(existing)
            manage_url = build_subscription_manage_url(existing)
            weekly_briefing_status = _sync_weekly_briefing_opt_in(
                normalized_email,
                opted_in=subscribe_weekly_briefing,
            )
            logger.info(
                "property_record_alert.subscribe_already_exists",
                extra={
                    "subscription_id": existing.pk,
                    "email": normalized_email,
                    "parcel_id": parcel_id,
                    "weekly_briefing_opt_in": subscribe_weekly_briefing,
                    "weekly_briefing_subscribed": weekly_briefing_status["weekly_briefing_subscribed"],
                },
            )
            return JsonResponse(
                {
                    "ok": True,
                    "already_exists": True,
                    "manage_url": manage_url,
                    "email": normalized_email,
                    "processed_count": 1,
                    "created_count": 0,
                    "reactivated_count": 0,
                    "unchanged_count": 1,
                    "created": False,
                    "reactivated": False,
                    "subscription": serialized,
                    "subscriptions": [serialized],
                    "results": [
                        {
                            "parcel_id": parcel_id,
                            "created": False,
                            "reactivated": False,
                            "already_exists": True,
                            "manage_url": manage_url,
                        }
                    ],
                    "signup_confirmation_sent": False,
                    **weekly_briefing_status,
                }
            )

    active_subscription_count = PropertyRecordAlertSubscription.objects.filter(
        email=normalized_email,
        is_active=True,
    ).count()
    inactive_to_activate = sum(
        1
        for parcel_id in normalized_parcel_ids
        if (parcel_id in existing_by_parcel and not existing_by_parcel[parcel_id].is_active)
    )
    new_to_create = sum(1 for parcel_id in normalized_parcel_ids if parcel_id not in existing_by_parcel)
    projected_active_total = active_subscription_count + inactive_to_activate + new_to_create

    if (
        projected_active_total > PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES
        and projected_active_total > active_subscription_count
    ):
        logger.warning(
            "property_record_alert.subscribe_watch_limit_reached",
            extra={
                "email": normalized_email,
                "active_subscription_count": active_subscription_count,
                "requested_parcel_count": len(normalized_parcel_ids),
                "projected_active_total": projected_active_total,
                "max_active_watches": PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES,
            },
        )
        return JsonResponse(
            {
                "error": "Watch limit reached.",
                "details": {
                    "email": (
                        f"You can track up to {PROPERTY_RECORD_ALERT_MAX_ACTIVE_WATCHES} "
                        "parcels per email."
                    ),
                },
            },
            status=400,
        )

    parcel_histories = ParcelHistory.objects.filter(parcel_number__in=normalized_parcel_ids)
    parcel_history_by_number = {
        history.parcel_number: history for history in parcel_histories
    }

    now = timezone.now()
    created_count = 0
    reactivated_count = 0
    operation_results: list[dict[str, Any]] = []
    serialized_subscriptions: list[dict[str, Any]] = []
    signup_email_sections: list[dict[str, Any]] = []

    for parcel_id in normalized_parcel_ids:
        parcel = parcels_by_number[parcel_id]
        parcel_history = parcel_history_by_number.get(parcel_id)
        cached_documents = (
            parcel_history.recording_documents
            if parcel_history and isinstance(parcel_history.recording_documents, list)
            else []
        )
        history_latest_number = (
            _safe_trimmed_text(getattr(parcel_history, "recording_latest_number", ""))
            if parcel_history
            else ""
        )
        history_latest_recorded_date = (
            getattr(parcel_history, "recording_latest_recorded_date", None)
            if parcel_history
            else None
        )
        latest_document_url = ""
        latest_legal_fragment = ""
        if cached_documents:
            latest_document = cached_documents[0]
            latest_document_url = _safe_trimmed_text(latest_document.get("document_url"))
            latest_legal_fragment = _safe_trimmed_text(latest_document.get("legal"), max_length=255)
            if not history_latest_number:
                history_latest_number = _safe_trimmed_text(
                    latest_document.get("recording_number")
                )
            if history_latest_recorded_date is None:
                history_latest_recorded_date = _as_iso_date(
                    latest_document.get("recorded_date") or ""
                )

        existing_subscription = existing_by_parcel.get(parcel_id)
        created = False
        reactivated = False
        latest_source_url = build_recording_results_url(parcel_id)

        if existing_subscription:
            subscription = existing_subscription
        else:
            subscription = PropertyRecordAlertSubscription(
                email=normalized_email,
                parcel=parcel,
                is_active=True,
            )
            created = True

        should_reset_baseline = created or not subscription.is_active
        if not created and not subscription.is_active:
            reactivated = True
        subscription.is_active = True

        if should_reset_baseline:
            context_values = parcel_contexts.get(parcel_id, {})
            owner_name = _safe_trimmed_text(
                context_values.get("owner_name"),
                max_length=255,
            )
            situs_address = _safe_trimmed_text(
                context_values.get("situs_address"),
                max_length=300,
            )

            if not owner_name or not situs_address:
                fallback_baseline = fetch_assessor_baseline_fallback(parcel_id)
                if not owner_name:
                    owner_name = _safe_trimmed_text(
                        fallback_baseline.get("owner_name"),
                        max_length=255,
                    )
                if not situs_address:
                    situs_address = _safe_trimmed_text(
                        fallback_baseline.get("situs_address") or parcel.situs_address,
                        max_length=300,
                    )

            subscription.baseline_owner_name = owner_name
            subscription.baseline_situs_address = situs_address
            subscription.baseline_legal_fragment = latest_legal_fragment
            subscription.monitored_names = _normalize_monitored_names(
                monitored_names_raw,
                baseline_owner_name=owner_name,
            )
            subscription.baseline_recording_number = history_latest_number
            subscription.baseline_recorded_date = history_latest_recorded_date
            subscription.last_notified_recording_number = history_latest_number
            subscription.last_alert_sent_at = None
        elif monitored_names_raw not in {None, ""}:
            subscription.monitored_names = _normalize_monitored_names(
                monitored_names_raw,
                baseline_owner_name=subscription.baseline_owner_name,
            )

        subscription.last_checked_at = now
        subscription.save()

        if created:
            created_count += 1
        if reactivated:
            reactivated_count += 1

        serialized = serialize_subscription(subscription)
        serialized_subscriptions.append(serialized)
        operation_results.append(
            {
                "parcel_id": parcel_id,
                "created": created,
                "reactivated": reactivated,
                "already_exists": bool(not created and not reactivated and subscription.is_active),
                "manage_url": build_subscription_manage_url(subscription),
            }
        )
        signup_email_sections.append(
            {
                "parcel_id": subscription.parcel_id,
                "owner_name": subscription.baseline_owner_name,
                "situs_address": subscription.baseline_situs_address,
                "monitored_names": list(getattr(subscription, "monitored_names", []) or []),
                "is_active": subscription.is_active,
                "manage_url": build_subscription_manage_url(subscription),
                "delete_url": build_subscription_delete_url(subscription),
                "recording_results_url": latest_source_url,
                "latest_document_url": latest_document_url,
                "baseline_recording_number": subscription.baseline_recording_number,
            }
        )

    unchanged_count = len(serialized_subscriptions) - created_count - reactivated_count
    response_payload: dict[str, Any] = {
        "ok": True,
        "email": normalized_email,
        "processed_count": len(serialized_subscriptions),
        "created_count": created_count,
        "reactivated_count": reactivated_count,
        "unchanged_count": unchanged_count,
        "results": operation_results,
        "subscriptions": serialized_subscriptions,
    }

    if len(serialized_subscriptions) == 1:
        single_result = operation_results[0]
        response_payload["created"] = single_result["created"]
        response_payload["reactivated"] = single_result["reactivated"]
        response_payload["already_exists"] = single_result.get("already_exists", False)
        response_payload["manage_url"] = single_result.get("manage_url")
        response_payload["subscription"] = serialized_subscriptions[0]

    signup_confirmation_sent = False
    try:
        sent_count = send_property_record_alert_signup_confirmation(
            email=normalized_email,
            parcel_subscriptions=signup_email_sections,
        )
        signup_confirmation_sent = sent_count > 0
        logger.info(
            "property_record_alert.signup_confirmation_send_succeeded",
            extra={
                "email": normalized_email,
                "parcel_count": len(signup_email_sections),
                "sent_count": sent_count,
            },
        )
    except Exception:
        logger.exception(
            "property_record_alert.signup_confirmation_send_failed",
            extra={"email": normalized_email, "parcel_count": len(signup_email_sections)},
        )
    weekly_briefing_status = _sync_weekly_briefing_opt_in(
        normalized_email,
        opted_in=subscribe_weekly_briefing,
    )
    response_payload.update(weekly_briefing_status)
    response_payload["signup_confirmation_sent"] = signup_confirmation_sent
    logger.info(
        "property_record_alert.subscribe_completed",
        extra={
            "email": normalized_email,
            "processed_count": response_payload["processed_count"],
            "created_count": created_count,
            "reactivated_count": reactivated_count,
            "unchanged_count": unchanged_count,
            "signup_confirmation_sent": signup_confirmation_sent,
            "weekly_briefing_opt_in": subscribe_weekly_briefing,
            "weekly_briefing_subscribed": weekly_briefing_status["weekly_briefing_subscribed"],
            "weekly_briefing_created": weekly_briefing_status["weekly_briefing_created"],
        },
    )

    return JsonResponse(response_payload)


@require_POST
def property_record_alert_parcel_preview(request):
    payload = _load_request_payload(request)
    parcel_raw = str(payload.get("parcel_id") or payload.get("parcel") or "").strip()
    parcel_id = normalize_parcel_id(parcel_raw)
    if not parcel_id:
        logger.warning(
            "property_record_alert.parcel_preview_invalid_request",
            extra={"parcel_raw": _safe_trimmed_text(parcel_raw, max_length=80)},
        )
        return JsonResponse(
            {
                "error": "Invalid request.",
                "details": {"parcel_id": "Parcel ID is required."},
            },
            status=400,
        )

    parcel = MasterParcel.objects.filter(parcel_number=parcel_id).first()
    if not parcel:
        logger.warning(
            "property_record_alert.parcel_preview_parcel_not_found",
            extra={"parcel_id": parcel_id},
        )
        return JsonResponse(
            {
                "error": "Parcel not found.",
                "details": {"parcel_id": "We couldn't find that parcel in our records."},
            },
            status=400,
        )

    baseline = resolve_assessor_baseline(parcel_id, timeout=3, prefer_live=False)
    owner_name = (baseline.get("owner_name") or "").strip()
    situs_address = (baseline.get("situs_address") or "").strip() or (parcel.situs_address or "").strip()
    logger.info(
        "property_record_alert.parcel_preview_succeeded",
        extra={
            "parcel_id": parcel_id,
            "source": baseline.get("source") or "db",
            "owner_present": bool(owner_name),
            "address_present": bool(situs_address),
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "parcel": {
                "parcel_id": parcel_id,
                "owner_name": owner_name,
                "situs_address": situs_address,
                "source": baseline.get("source") or "db",
            },
        }
    )


@require_http_methods(["GET", "POST"])
def property_record_alert_unsubscribe(request, token: str):
    subscription = PropertyRecordAlertSubscription.from_unsubscribe_token(
        token,
        max_age=PROPERTY_RECORD_ALERT_UNSUBSCRIBE_MAX_AGE_SECONDS,
    )
    if not subscription:
        status = "invalid"
    elif request.method == "POST":
        subscription.is_active = False
        subscription.save(update_fields=["is_active", "updated_at"])
        status = "success"
    else:
        status = "confirm"

    context = _basic_page_context(
        request,
        "Parcel Recorded Document Alerts unsubscribe",
        "Manage your parcel recorded document alert subscription.",
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context.update({"status": status, "subscription": subscription})
    return render(
        request,
        "openskagit/property_record_alert_unsubscribe.html",
        context,
    )


@require_http_methods(["GET", "POST"])
def property_record_alert_manage(request, token: str):
    subscription = PropertyRecordAlertSubscription.from_manage_token(
        token,
        max_age=PROPERTY_RECORD_ALERT_MANAGE_MAX_AGE_SECONDS,
    )

    status = "ready"
    details: dict[str, str] = {}
    if not subscription:
        status = "invalid"
    elif request.method == "POST":
        email_raw = str(request.POST.get("email") or "").strip()
        is_active = _is_truthy(request.POST.get("is_active"))
        monitored_names_raw = request.POST.get("monitored_names")
        details = _update_property_record_alert_subscription(
            subscription=subscription,
            email_raw=email_raw,
            is_active=is_active,
            monitored_names_raw=monitored_names_raw,
        )
        status = "saved" if not details else "error"

    context = _basic_page_context(
        request,
        "Manage parcel recorded document alert",
        "Edit or delete a parcel recorded document alert without logging in.",
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context.update(
        {
            "status": status,
            "details": details,
            "subscription": subscription,
            "manage_token": token,
            "delete_url": reverse("property-record-alert-delete", args=[token]),
            "monitored_names_text": "\n".join(
                _normalize_monitored_names(
                    getattr(subscription, "monitored_names", []),
                    baseline_owner_name=getattr(subscription, "baseline_owner_name", ""),
                )
            )
            if subscription
            else "",
        }
    )
    return render(
        request,
        "openskagit/property_record_alert_manage.html",
        context,
    )


@require_POST
def property_record_alert_manage_api(request, token: str):
    subscription = PropertyRecordAlertSubscription.from_manage_token(
        token,
        max_age=PROPERTY_RECORD_ALERT_MANAGE_MAX_AGE_SECONDS,
    )
    if not subscription:
        return JsonResponse(
            {
                "error": "Invalid link.",
                "details": {"token": "The manage link is invalid or expired."},
            },
            status=400,
        )

    payload = _load_request_payload(request)
    email_raw = str(payload.get("email") or "").strip()
    is_active = _is_truthy(payload.get("is_active"))
    monitored_names_raw = payload.get("monitored_names")
    details = _update_property_record_alert_subscription(
        subscription=subscription,
        email_raw=email_raw,
        is_active=is_active,
        monitored_names_raw=monitored_names_raw,
    )
    if details:
        return JsonResponse(
            {
                "error": "Invalid request.",
                "details": details,
            },
            status=400,
        )

    return JsonResponse(
        {
            "ok": True,
            "subscription": serialize_subscription(subscription),
        }
    )


@require_GET
def property_record_alert_delete(request, token: str):
    subscription = PropertyRecordAlertSubscription.from_manage_token(
        token,
        max_age=PROPERTY_RECORD_ALERT_MANAGE_MAX_AGE_SECONDS,
    )
    if not subscription:
        status = "invalid"
    elif subscription.is_active:
        subscription.is_active = False
        subscription.save(update_fields=["is_active", "updated_at"])
        status = "deleted"
    else:
        status = "already_deleted"

    context = _basic_page_context(
        request,
        "Parcel alert deleted",
        "This parcel recorded document alert has been removed.",
    )
    canonical = request.build_absolute_uri()
    context["canonical_url"] = canonical
    context["og_url"] = canonical
    context.update({"status": status, "subscription": subscription})
    return render(
        request,
        "openskagit/property_record_alert_delete.html",
        context,
    )
