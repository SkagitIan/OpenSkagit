from __future__ import annotations

import html
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup
from django.db import connection
from django.utils import timezone

from openskagit.models import MasterParcel

logger = logging.getLogger(__name__)

FILL_PAGE_URL = "https://www.skagitcounty.net/search/property/Webservice.asmx/fillPage"
SEARCH_URL = "https://www.skagitcounty.net/search/property/"

DELINQUENT_TOTAL_KEY = "Delinquent Taxes, Interest, and Penalty TOTAL"

TAX_STATUS_CONFIRMED_DELINQUENT = "confirmed_delinquent"
TAX_STATUS_NOT_DELINQUENT = "not_delinquent_now"
TAX_STATUS_VERIFY_ERROR = "verify_error"

TAX_STATUS_CHOICES = (
    TAX_STATUS_CONFIRMED_DELINQUENT,
    TAX_STATUS_NOT_DELINQUENT,
    TAX_STATUS_VERIFY_ERROR,
)

_thread_local = threading.local()


def _parse_money(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    clean = (
        text.replace("$", "")
        .replace(",", "")
        .replace("(", "-")
        .replace(")", "")
        .replace("+", "")
        .strip()
    )
    if not clean:
        return None
    try:
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.get(SEARCH_URL, timeout=20)
        _thread_local.session = session
    return session


def _extract_tax_summary(decoded_html: str) -> Dict[str, str]:
    soup = BeautifulSoup(decoded_html, "html.parser")
    summary: Dict[str, str] = {}

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) == 2 and cells[0]:
                summary[cells[0].rstrip(":")] = cells[1]

    return summary


def _fetch_live_tax_summary(parcel_number: str, timeout_seconds: int = 30) -> Dict[str, str]:
    session = _get_thread_session()
    session.cookies.clear()
    session.cookies.set(
        "prophistory",
        f"{parcel_number},",
        domain="www.skagitcounty.net",
        path="/",
    )

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
        "Referer": SEARCH_URL,
        "Origin": "https://www.skagitcounty.net",
    }

    nav_body = "{ 'sValue': '" + parcel_number + ",','ResultType': 'nav' }"
    session.post(FILL_PAGE_URL, data=nav_body, headers=headers, timeout=timeout_seconds)

    tax_body = "{ 'sValue': '" + parcel_number + "','ResultType': 'Taxes' }"
    tax_response = session.post(FILL_PAGE_URL, data=tax_body, headers=headers, timeout=timeout_seconds)
    tax_response.raise_for_status()

    try:
        payload = tax_response.json().get("d", "")
    except Exception:
        payload = tax_response.text

    decoded = html.unescape(payload)
    summary = _extract_tax_summary(decoded)
    if not summary:
        raise RuntimeError("Live tax response had no summary rows.")
    return summary


def _candidate_sql() -> str:
    return """
WITH tax_flags AS (
    SELECT
        ph.parcel_number,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS delinquent_total,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS total_due,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS amount_paid
    FROM openskagit_parcelhistory ph
),
res AS (
    SELECT
        mp.parcel_number,
        mp.situs_address,
        po.owner_name,
        mp.land_use_code,
        mp.land_use_description,
        mp.condition_score,
        mp.quality_score,
        COALESCE(mp.final_year_built, mp.year_built) AS year_built,
        mp.assessed_value,
        tf.delinquent_total,
        tf.total_due,
        tf.amount_paid,
        CASE
            WHEN tf.total_due > 0 THEN tf.delinquent_total / tf.total_due
            ELSE NULL
        END AS delinquency_years_proxy
    FROM master_parcel mp
    JOIN tax_flags tf ON tf.parcel_number = mp.parcel_number
    LEFT JOIN parcel_owner po ON po.parcel_id = mp.parcel_number
    WHERE (%s = FALSE OR mp.land_use_code = ANY(%s))
)
SELECT
    parcel_number,
    situs_address,
    owner_name,
    land_use_code,
    land_use_description,
    condition_score,
    quality_score,
    year_built,
    assessed_value,
    delinquent_total,
    total_due,
    amount_paid,
    delinquency_years_proxy
FROM res
WHERE delinquent_total > 0
  AND delinquent_total >= %s
  AND COALESCE(delinquency_years_proxy, 0) >= %s
ORDER BY delinquent_total DESC, delinquency_years_proxy DESC, parcel_number
LIMIT %s
    """


def find_candidate_parcels(
    *,
    tax_year: int,
    min_delinquent: Decimal,
    min_ratio: float,
    limit: int,
    land_use_codes: List[str],
) -> List[Dict[str, Any]]:
    due_key = f"{tax_year} Total Due"
    paid_key = f"{tax_year} Amount Paid"
    apply_land_use_filter = bool(land_use_codes)

    with connection.cursor() as cursor:
        cursor.execute(
            _candidate_sql(),
            [
                DELINQUENT_TOTAL_KEY,
                due_key,
                paid_key,
                apply_land_use_filter,
                land_use_codes,
                min_delinquent,
                min_ratio,
                limit,
            ],
        )
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def _verify_candidate(parcel_row: Dict[str, Any], tax_year: int) -> Dict[str, Any]:
    parcel_number = str(parcel_row["parcel_number"])
    due_key = f"{tax_year} Total Due"
    paid_key = f"{tax_year} Amount Paid"
    started = time.monotonic()

    result: Dict[str, Any] = dict(parcel_row)
    result["live_delinquent_total"] = None
    result["live_total_due"] = None
    result["live_amount_paid"] = None
    result["verify_error"] = ""

    try:
        summary = _fetch_live_tax_summary(parcel_number)
        live_delinquent = _parse_money(summary.get(DELINQUENT_TOTAL_KEY))
        live_due = _parse_money(summary.get(due_key))
        live_paid = _parse_money(summary.get(paid_key))

        result["live_delinquent_total"] = live_delinquent
        result["live_total_due"] = live_due
        result["live_amount_paid"] = live_paid

        if live_delinquent is not None and live_delinquent > 0:
            result["tax_status"] = TAX_STATUS_CONFIRMED_DELINQUENT
        else:
            result["tax_status"] = TAX_STATUS_NOT_DELINQUENT
    except Exception as exc:
        logger.warning("Live verify failed for %s: %s", parcel_number, exc)
        result["tax_status"] = TAX_STATUS_VERIFY_ERROR
        result["verify_error"] = str(exc)[:500]

    result["verify_seconds"] = round(time.monotonic() - started, 3)
    return result


def _persist_tax_status(results: List[Dict[str, Any]]) -> int:
    if not results:
        return 0

    by_parcel = {str(item["parcel_number"]): item for item in results if item.get("tax_status")}
    if not by_parcel:
        return 0

    now = timezone.now()
    to_update = []
    for parcel in MasterParcel.objects.filter(parcel_number__in=list(by_parcel.keys())).only(
        "parcel_number",
        "tax_status",
        "tax_status_updated_at",
    ):
        row = by_parcel.get(parcel.parcel_number)
        if row is None:
            continue
        new_status = row["tax_status"]
        if new_status not in TAX_STATUS_CHOICES:
            continue
        parcel.tax_status = new_status
        parcel.tax_status_updated_at = now
        to_update.append(parcel)

    if to_update:
        MasterParcel.objects.bulk_update(to_update, ["tax_status", "tax_status_updated_at"])
    return len(to_update)


def run_tax_foreclosure_scan_and_verify(
    *,
    tax_year: int,
    min_delinquent: Decimal,
    min_ratio: float,
    candidate_limit: int,
    max_workers: int,
    land_use_codes: List[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    started = time.monotonic()
    candidates = find_candidate_parcels(
        tax_year=tax_year,
        min_delinquent=min_delinquent,
        min_ratio=min_ratio,
        limit=candidate_limit,
        land_use_codes=land_use_codes,
    )

    if not candidates:
        summary = {
            "tax_year": tax_year,
            "candidate_count": 0,
            "verified_count": 0,
            "confirmed_count": 0,
            "cleared_count": 0,
            "error_count": 0,
            "updated_count": 0,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        return summary, []

    workers = max(1, min(max_workers, 20))
    verified: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_verify_candidate, candidate, tax_year): candidate["parcel_number"]
            for candidate in candidates
        }
        for future in as_completed(future_map):
            verified.append(future.result())

    verified.sort(
        key=lambda row: (
            0 if row.get("tax_status") == TAX_STATUS_CONFIRMED_DELINQUENT else 1,
            -(row.get("live_delinquent_total") or row.get("delinquent_total") or Decimal("0")),
            row.get("parcel_number") or "",
        )
    )

    updated_count = _persist_tax_status(verified)
    summary = {
        "tax_year": tax_year,
        "candidate_count": len(candidates),
        "verified_count": len(verified),
        "confirmed_count": sum(1 for row in verified if row.get("tax_status") == TAX_STATUS_CONFIRMED_DELINQUENT),
        "cleared_count": sum(1 for row in verified if row.get("tax_status") == TAX_STATUS_NOT_DELINQUENT),
        "error_count": sum(1 for row in verified if row.get("tax_status") == TAX_STATUS_VERIFY_ERROR),
        "updated_count": updated_count,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    return summary, verified
