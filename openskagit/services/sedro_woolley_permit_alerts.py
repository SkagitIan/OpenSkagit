from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional, Sequence

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from openskagit.models import MasterParcel, SedroWoolleyPermit, SedroWoolleyPermitAlertRun


ALERT_PERMIT_TYPE_ALLOWLIST = frozenset(
    {
        "demolition",
        "demolision",
        "residential roof",
        "building residential",
        "building commercial",
        "residential and commercial",
        "building residential and commercial",
        "building commercial and residential",
    }
)


@dataclass(frozen=True)
class PermitAlertPayload:
    subject: str
    text: str
    html: str
    permit_count: int


def parse_recipients(raw_values: Iterable[str]) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()

    for raw in raw_values:
        if not raw:
            continue
        for part in str(raw).replace(";", ",").split(","):
            email = part.strip().lower()
            if not email or "@" not in email:
                continue
            if email in seen:
                continue
            seen.add(email)
            recipients.append(email)

    return recipients


def recipients_from_env(env_var: str = "SW_PERMIT_ALERT_RECIPIENTS") -> list[str]:
    raw = os.getenv(env_var, "")
    return parse_recipients([str(raw)])


def last_successful_alert_watermark(job_name: str = "nightly_sw_permit_alert") -> Optional[datetime]:
    return (
        SedroWoolleyPermitAlertRun.objects.filter(
            job_name=job_name,
            success=True,
            watermark_to__isnull=False,
        )
        .order_by("-watermark_to")
        .values_list("watermark_to", flat=True)
        .first()
    )


def _normalize_permit_type(value: str) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .replace("&", " and ")
        .replace("/", " and ")
        .replace("-", " ")
        .split()
    )


def is_alert_permit_type(permit_type: str) -> bool:
    return _normalize_permit_type(permit_type) in ALERT_PERMIT_TYPE_ALLOWLIST


def fetch_new_important_permits(
    *,
    since_exclusive: Optional[datetime] = None,
    until_inclusive: Optional[datetime] = None,
    permit_date_start: Optional[date] = None,
    permit_date_end: Optional[date] = None,
    max_items: int = 100,
) -> list[SedroWoolleyPermit]:
    qs = SedroWoolleyPermit.objects.select_related("parcel")
    if until_inclusive is not None:
        qs = qs.filter(created_at__lte=until_inclusive)
    if since_exclusive is not None:
        qs = qs.filter(created_at__gt=since_exclusive)
    if permit_date_start is not None:
        qs = qs.filter(permit_date__gte=permit_date_start)
    if permit_date_end is not None:
        qs = qs.filter(permit_date__lte=permit_date_end)

    limit = max(1, min(max_items, 500))
    permits: list[SedroWoolleyPermit] = []
    for permit in qs.order_by("-created_at", "-permit_date", "-updated_at"):
        if not is_alert_permit_type(getattr(permit, "permit_type", "")):
            continue
        permits.append(permit)
        if len(permits) >= limit:
            break
    return permits


def _raw_payload_parcel_number(permit: SedroWoolleyPermit) -> str:
    raw_payload = getattr(permit, "raw_payload", {})
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else {}
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    for value in (detail.get("parcel_number"), summary.get("parcel_number")):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _candidate_addresses(site_address: str) -> list[str]:
    raw = str(site_address or "").strip()
    if not raw:
        return []
    candidates = [raw]
    if "," in raw:
        first = raw.split(",", 1)[0].strip()
        if first and first.lower() != raw.lower():
            candidates.append(first)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _lookup_parcel_by_address(address: str, cache: dict[str, Optional[str]]) -> Optional[str]:
    key = address.strip().lower()
    if not key:
        return None
    if key in cache:
        return cache[key]

    matches = list(
        MasterParcel.objects.filter(
            city_district="SEDRO WOOLLEY",
            situs_address__iexact=address.strip(),
        )
        .values_list("parcel_number", flat=True)[:2]
    )
    parcel_number = matches[0] if len(matches) == 1 else None
    cache[key] = parcel_number
    return parcel_number


def _best_effort_parcel_number(
    permit: SedroWoolleyPermit,
    *,
    address_lookup_cache: dict[str, Optional[str]],
) -> str:
    parcel_id = getattr(permit, "parcel_id", None)
    if parcel_id:
        return str(parcel_id).strip()

    raw_parcel = _raw_payload_parcel_number(permit)
    if raw_parcel:
        return raw_parcel

    for candidate in _candidate_addresses(getattr(permit, "site_address", "") or ""):
        parcel_number = _lookup_parcel_by_address(candidate, address_lookup_cache)
        if parcel_number:
            return parcel_number
    return ""


def _permit_rows_for_email(permits: Sequence[SedroWoolleyPermit]) -> list[dict]:
    address_lookup_cache: dict[str, Optional[str]] = {}
    rows: list[dict] = []
    for permit in permits:
        work_description = str(getattr(permit, "work_description", "") or "").strip()
        work_short = work_description
        if len(work_short) > 220:
            work_short = work_short[:217].rstrip() + "..."
        rows.append(
            {
                "permit_number": str(permit.permit_number or permit.external_id or "").strip(),
                "external_id": getattr(permit, "external_id", ""),
                "permit_type": str(getattr(permit, "permit_type", "") or "").strip(),
                "permit_date": getattr(permit, "permit_date", None),
                "site_address": str(getattr(permit, "site_address", "") or "").strip(),
                "status": str(getattr(permit, "status", "") or "").strip(),
                "total_fees": getattr(permit, "total_fees", None),
                "detail_url": str(getattr(permit, "detail_url", "") or "").strip(),
                "parcel_number": _best_effort_parcel_number(
                    permit,
                    address_lookup_cache=address_lookup_cache,
                ),
                "work_description": work_description,
                "work_description_short": work_short,
            }
        )
    return rows


def build_permit_alert_payload(
    permits: Sequence[SedroWoolleyPermit],
    *,
    watermark_from: Optional[datetime],
    watermark_to: datetime,
    permit_date_start: Optional[date] = None,
    permit_date_end: Optional[date] = None,
) -> PermitAlertPayload:
    permit_count = len(permits)
    if permit_count == 0:
        subject = "Sedro-Woolley permits: no new important permits"
    elif permit_count == 1:
        subject = "Sedro-Woolley permits: 1 new important permit"
    else:
        subject = f"Sedro-Woolley permits: {permit_count} new important permits"

    permit_rows = _permit_rows_for_email(permits)
    context = {
        "permits": permit_rows,
        "permit_count": permit_count,
        "watermark_from": watermark_from,
        "watermark_to": watermark_to,
        "permit_date_start": permit_date_start,
        "permit_date_end": permit_date_end,
        "site_url": settings.SITE_URL.rstrip("/"),
        "portal_url": f"{settings.SITE_URL.rstrip('/')}/sedro-woolley/",
        "zoning_map_url": f"{settings.SITE_URL.rstrip('/')}/maps/sedro-woolley/zoning/",
        "generated_at": timezone.now(),
    }
    text = render_to_string("openskagit/emails/sw_permit_alert.txt", context)
    html = render_to_string("openskagit/emails/sw_permit_alert.html", context)
    return PermitAlertPayload(subject=subject, text=text, html=html, permit_count=permit_count)


def send_permit_alert_email(
    *,
    recipients: Sequence[str],
    payload: PermitAlertPayload,
    from_email: Optional[str] = None,
) -> int:
    if not recipients:
        return 0

    message = EmailMultiAlternatives(
        subject=payload.subject,
        body=payload.text,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=list(recipients),
    )
    message.attach_alternative(payload.html, "text/html")
    message.send()
    return len(recipients)
