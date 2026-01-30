from __future__ import annotations

import hashlib
import json
import statistics
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone
from django.utils.html import escape, strip_tags

from openskagit.neighborhood import get_neighborhood_snapshot
from . import llm
from .models import MasterParcel, ParcelHistory


COUNTY_ETR_CACHE_TTL = 60 * 60 * 6  # 6 hours
COUNTY_ETR_SNAPSHOT_PATH = Path(settings.BASE_DIR) / "data" / "county_etr_stats.json"

VALUE_BRACKET_DEFINITIONS = [
    {"label": "Under $250k", "min_value": 0, "max_value": 250_000},
    {"label": "$250k–$400k", "min_value": 250_000, "max_value": 400_000},
    {"label": "$400k–$600k", "min_value": 400_000, "max_value": 600_000},
    {"label": "$600k–$800k", "min_value": 600_000, "max_value": 800_000},
    {"label": "$800k+", "min_value": 800_000, "max_value": None},
]

TAX_AI_SUMMARY_KEY = "ai_tax_summary"
TAX_AI_PROMPT_VERSION = "tax-ai-summary-v2"
TAX_AI_MODEL_NAME = "gpt-5"
TAX_AI_ALLOWED_YEARS = {2025, 2026}
TAX_AI_IN_PROGRESS_TTL = 60 * 10
TAX_AI_FAILURE_RETRY_SECONDS = 60 * 10

REFERENCE_INFLATION_RATES = {
    2018: 0.020,
    2019: 0.018,
    2020: 0.014,
    2021: 0.071,
    2022: 0.065,
    2023: 0.032,
    2024: 0.034,
    2025: 0.032,
}
DEFAULT_INFLATION_RATE = 0.03


def _parse_history_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    clean = text.replace("$", "").replace(",", "")
    if not clean:
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def _extract_history_year(row: Dict[str, Any]) -> Optional[int]:
    year_raw = row.get("VALUE YEAR") or row.get("TAX YEAR")
    if not year_raw:
        return None
    try:
        return int(str(year_raw).strip())
    except (TypeError, ValueError):
        return None


def _extract_history_value(row: Dict[str, Any]) -> Optional[float]:
    for key in ("MARKET TOTAL", "ASSESSED TOTAL", "TAXABLE VALUE"):
        value = _parse_history_money(row.get(key))
        if value is not None:
            return value
    return None


def _extract_history_tax(row: Dict[str, Any]) -> Optional[float]:
    for key in ("TAX", "PROPERTY TAX", "TOTAL TAX"):
        value = _parse_history_money(row.get(key))
        if value is not None:
            return value
    return None


def _coerce_history_rows(rows: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except Exception:
            return None
    if not isinstance(rows, list):
        return None
    return [row for row in rows if isinstance(row, dict)]


def _tax_value_for_year(rows: Any, target_year: int) -> Optional[Tuple[float, float]]:
    parsed = _coerce_history_rows(rows)
    if not parsed:
        return None
    for row in parsed:
        year = _extract_history_year(row)
        if year != target_year:
            continue
        tax = _extract_history_tax(row)
        value = _extract_history_value(row)
        if tax is None or value is None:
            continue
        if value <= 0 or tax <= 0:
            continue
        return float(tax), float(value)
    return None


def _bracket_label_for_value(value: float) -> Optional[str]:
    for definition in VALUE_BRACKET_DEFINITIONS:
        lower = definition["min_value"]
        upper = definition["max_value"]
        if value >= lower and (upper is None or value < upper):
            return definition["label"]
    return None


def _load_county_etr_snapshot() -> Dict[str, Any]:
    if not COUNTY_ETR_SNAPSHOT_PATH.exists():
        return {}
    try:
        with COUNTY_ETR_SNAPSHOT_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _compute_county_etr_insights(target_year: int) -> Optional[Dict[str, Any]]:
    values: List[float] = []
    bracket_stats: Dict[str, Dict[str, float]] = {
        definition["label"]: {"sum": 0.0, "count": 0}
        for definition in VALUE_BRACKET_DEFINITIONS
    }

    for record in ParcelHistory.objects.only("rows").iterator():
        pair = _tax_value_for_year(record.rows, target_year)
        if not pair:
            continue
        tax_value, market_value = pair
        if market_value <= 0 or tax_value <= 0:
            continue
        etr = tax_value / market_value
        values.append(etr)
        label = _bracket_label_for_value(market_value)
        if label:
            bucket = bracket_stats[label]
            bucket["sum"] += etr
            bucket["count"] += 1

    if not values:
        return None

    median = statistics.median(values)
    bracket_summary: List[Dict[str, Any]] = []
    for definition in VALUE_BRACKET_DEFINITIONS:
        stats = bracket_stats[definition["label"]]
        avg = stats["sum"] / stats["count"] if stats["count"] else None
        bracket_summary.append(
            {
                "label": definition["label"],
                "min_value": definition["min_value"],
                "max_value": definition["max_value"],
                "count": stats["count"],
                "avg_etr": float(avg) if avg is not None else None,
            }
        )

    regressivity_score: Optional[float] = None
    direction = "unknown"
    low_avg = next((entry["avg_etr"] for entry in bracket_summary if entry["avg_etr"] is not None), None)
    high_avg = next(
        (entry["avg_etr"] for entry in reversed(bracket_summary) if entry["avg_etr"] is not None),
        None,
    )
    if low_avg is not None and high_avg is not None:
        delta = (low_avg - high_avg) * 100.0
        regressivity_score = delta
        if delta > 0.0001:
            direction = "regressive"
        elif delta < -0.0001:
            direction = "progressive"
        else:
            direction = "neutral"

    return {
        "year": target_year,
        "count": len(values),
        "median": float(median),
        "brackets": bracket_summary,
        "regressivity_score": regressivity_score,
        "regressivity_direction": direction,
    }


def county_etr_insights(target_year: Optional[int]) -> Optional[Dict[str, Any]]:
    if target_year is None:
        return None
    cache_key = f"openskagit:county-etr:{target_year}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    snapshot = _load_county_etr_snapshot()
    key = str(target_year)
    if key in snapshot:
        payload = snapshot[key]
        if isinstance(payload, dict):
            cache.set(cache_key, payload, COUNTY_ETR_CACHE_TTL)
            return payload

    payload = _compute_county_etr_insights(target_year)
    if payload is None:
        return None
    cache.set(cache_key, payload, COUNTY_ETR_CACHE_TTL)
    return payload


def _coerce_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(val) for key, val in value.items()}
    return value


def _average_inflation_rate(start_year: int, end_year: int) -> float:
    if end_year <= start_year:
        return DEFAULT_INFLATION_RATE
    span = end_year - start_year
    factors = [
        1 + REFERENCE_INFLATION_RATES.get(year, DEFAULT_INFLATION_RATE)
        for year in range(start_year + 1, end_year + 1)
    ]
    if not factors:
        return DEFAULT_INFLATION_RATE
    total = 1.0
    for factor in factors:
        total *= factor
    return float(total ** (1 / span) - 1)


def _serialize_parcel(parcel: MasterParcel) -> Dict[str, Any]:
    return {
        "parcel_number": parcel.parcel_number,
        "address": parcel.situs_address,
        "hood_code": parcel.hood_code,
        "hood_description": parcel.hood_description,
        "proptype": parcel.proptype,
        "land_use_description": parcel.land_use_description,
        "assessed_value": parcel.assessed_value,
        "taxable_value": parcel.taxable_value,
        "total_market_value": parcel.total_market_value,
        "acres": parcel.acres,
        "year_built": parcel.year_built or parcel.eff_year_built,
        "living_area": parcel.living_area or parcel.final_living_area,
        "sale_price": parcel.sale_price,
    }


def _history_fingerprint(rows: Any, parcel_id: str) -> Optional[str]:
    parsed = _coerce_history_rows(rows)
    if not parsed:
        return None
    normalized = []
    for row in parsed:
        year = _extract_history_year(row)
        tax = _extract_history_tax(row)
        value = _extract_history_value(row)
        if year is None:
            continue
        normalized.append({"year": year, "tax": tax, "value": value})
    normalized.sort(key=lambda entry: entry["year"])
    payload = {"parcel_id": parcel_id, "history": normalized}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _payload_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _apply_markdown_bold(text: str) -> str:
    if "**" not in text:
        return text
    parts = text.split("**")
    if len(parts) < 3 or len(parts) % 2 == 0:
        return text
    out: List[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            out.append(f"<strong>{part}</strong>")
        else:
            out.append(part)
    return "".join(out)


def _sanitize_ai_summary_html(text: str) -> str:
    normalized = " ".join(text.split())
    normalized = _apply_markdown_bold(normalized)
    escaped = escape(normalized)
    escaped = escaped.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
    return escaped


def build_parcel_tax_story_payload(parcel_id: str) -> Optional[Dict[str, Any]]:
    master = (
        MasterParcel.objects.filter(parcel_number=parcel_id)
        .only("total_market_value")
        .first()
    )

    record = ParcelHistory.objects.only("rows").filter(parcel_number=parcel_id).first()
    rows = _coerce_history_rows(record.rows) if record else None
    if not rows:
        return None

    tax_history: List[Dict[str, Any]] = []
    for row in rows:
        year = _extract_history_year(row)
        tax_value = _extract_history_tax(row)
        if year is None or tax_value is None:
            continue
        tax_history.append(
            {
                "year": year,
                "tax": tax_value,
                "value": _extract_history_value(row),
            }
        )
    tax_history.sort(key=lambda entry: entry["year"])

    cumulative_taxes = sum(entry["tax"] for entry in tax_history)
    tax_trend_cagr = None
    inflation_avg = None
    tax_vs_inflation = None
    history_years = None
    if len(tax_history) >= 2:
        first = tax_history[0]
        last = tax_history[-1]
        span = last["year"] - first["year"]
        history_years = {"start": first["year"], "end": last["year"], "span": span}
        if span > 0 and first["tax"] > 0 and last["tax"] > 0:
            tax_trend_cagr = (last["tax"] / first["tax"]) ** (1 / span) - 1
            inflation_avg = _average_inflation_rate(first["year"], last["year"])
            tax_vs_inflation = tax_trend_cagr - inflation_avg

    total_market_value = None
    if tax_history:
        total_market_value = tax_history[-1].get("value")
    if total_market_value is None and master and master.total_market_value:
        try:
            total_market_value = float(master.total_market_value)
        except (TypeError, ValueError):
            total_market_value = None

    value_history_points = [
        {
            "year": entry["year"],
            "value": entry["value"],
        }
        for entry in tax_history
        if entry.get("year") is not None and entry.get("value") is not None
    ]
    value_history_points.sort(key=lambda item: item["year"])
    value_history_5y = value_history_points[-5:]

    annual_tax_points = []
    cumulative_total = 0.0
    for entry in tax_history:
        year = entry.get("year")
        tax_value = entry.get("tax")
        if year is None or tax_value is None:
            continue
        cumulative_total += tax_value
        annual_tax_points.append(
            {
                "year": year,
                "annual_tax": tax_value,
                "cumulative": cumulative_total,
            }
        )

    payload = {
        "parcel_id": parcel_id,
        "total_market_value": total_market_value,
        "cumulative_taxes_paid": cumulative_taxes,
        "tax_trend_cagr": tax_trend_cagr,
        "inflation_avg": inflation_avg,
        "tax_vs_inflation": tax_vs_inflation,
        "history_years": history_years,
        "value_history_5y": value_history_5y,
        "annual_tax_points": annual_tax_points,
        "source": "parcel_history_rows",
    }

    return _normalize(payload)


def build_parcel_tax_fairness_payload(parcel_id: str, tax_year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    history = (
        ParcelHistory.objects.filter(parcel_number=parcel_id)
        .only("rows")
        .first()
    )
    if not history:
        return None

    rows = _coerce_history_rows(history.rows)
    if not rows:
        return None

    row_years = {
        year for row in rows
        if (year := _extract_history_year(row)) in TAX_AI_ALLOWED_YEARS
    }
    candidate_year = None
    if tax_year in TAX_AI_ALLOWED_YEARS and tax_year in row_years:
        candidate_year = tax_year
    elif row_years:
        candidate_year = max(row_years)

    if candidate_year is None:
        return None

    subject_pair = _tax_value_for_year(history.rows, candidate_year)
    if not subject_pair:
        return None

    subject_tax, subject_value = subject_pair
    subject_etr = subject_tax / subject_value if subject_value else None
    if subject_etr is None:
        return None

    master = (
        MasterParcel.objects.filter(parcel_number=parcel_id)
        .only("parcel_number", "hood_code", "hood_description")
        .first()
    )
    hood_code = master.hood_code if master else None
    hood_description = master.hood_description or "" if master else ""
    if not hood_code:
        return None

    peer_parcels = MasterParcel.objects.filter(hood_code=hood_code).values_list("parcel_number", flat=True)
    peer_qs = ParcelHistory.objects.filter(parcel_number__in=peer_parcels).only("parcel_number", "rows")
    etrs: List[float] = []
    for record in peer_qs.iterator():
        pair = _tax_value_for_year(record.rows, candidate_year)
        if not pair:
            continue
        tax_value, assessed_value = pair
        etr = tax_value / assessed_value if assessed_value else None
        if etr is None or etr <= 0:
            continue
        etrs.append(etr)

    if not etrs:
        return None

    sorted_etrs = sorted(etrs)
    count = len(sorted_etrs)
    mid = count // 2
    if count % 2:
        median_etr = sorted_etrs[mid]
    else:
        median_etr = (sorted_etrs[mid - 1] + sorted_etrs[mid]) / 2.0
    mean_etr = sum(sorted_etrs) / count
    cod = None
    prd = None
    if median_etr:
        cod = (sum(abs(etr - median_etr) for etr in sorted_etrs) / (count * median_etr)) * 100
        prd = mean_etr / median_etr

    percentile = sum(1 for etr in sorted_etrs if etr <= subject_etr) / count

    payload = {
        "parcel_id": parcel_id,
        "tax_year": candidate_year,
        "hood_code": hood_code,
        "hood_description": hood_description,
        "sample_count": count,
        "subject_etr": subject_etr,
        "hood_min": sorted_etrs[0],
        "hood_max": sorted_etrs[-1],
        "hood_median": median_etr,
        "hood_mean": mean_etr,
        "cod": cod,
        "prd": prd,
        "neighbor_count": count,
        "subject_etr_percentile": percentile,
        "subject_etr_percentile_rank": round(percentile * 100, 1),
        "source": "parcel_history",
    }

    return _normalize(payload)


def build_tax_ai_payload(parcel_id: str) -> Optional[Dict[str, Any]]:
    parcel = (
        MasterParcel.objects.filter(parcel_number=parcel_id)
        .only(
            "parcel_number",
            "situs_address",
            "hood_code",
            "hood_description",
            "proptype",
            "land_use_description",
            "assessed_value",
            "taxable_value",
            "total_market_value",
            "acres",
            "year_built",
            "eff_year_built",
            "living_area",
            "final_living_area",
            "sale_price",
        )
        .first()
    )
    parcel_payload = _serialize_parcel(parcel) if parcel else None

    story_payload = build_parcel_tax_story_payload(parcel_id)
    if not story_payload:
        return None

    story_years = story_payload.get("history_years") or {}
    story_year = story_years.get("end")
    fairness_payload = build_parcel_tax_fairness_payload(parcel_id, story_year)

    county_year = story_year or (fairness_payload.get("tax_year") if fairness_payload else None)
    county_payload = county_etr_insights(county_year) if county_year else None

    hood_code = None
    if fairness_payload and fairness_payload.get("hood_code"):
        hood_code = fairness_payload.get("hood_code")
    elif parcel_payload:
        hood_code = parcel_payload.get("hood_code")

    neighborhood_snapshot = None
    if hood_code:
        neighborhood_snapshot = get_neighborhood_snapshot(hood_code, year=fairness_payload.get("tax_year") if fairness_payload else None)

    payload = {
        "parcel": parcel_payload,
        "tax_story": story_payload,
        "tax_fairness": fairness_payload,
        "county_etr": county_payload,
        "neighborhood_snapshot": neighborhood_snapshot,
    }

    return _normalize(payload)


def _summary_sentence(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    normalized = " ".join(str(text).split()).strip()
    if not normalized or normalized.lower() in {"null", "none", "n/a"}:
        return None
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def _render_tax_ai_summary(structured: Dict[str, Optional[str]]) -> str:
    rows: List[str] = []
    for label, key in (
        ("Parcel", "parcel"),
        ("Tax position", "tax_position"),
        ("County context", "county_context"),
        ("Neighborhood context", "neighborhood_context"),
        ("Trend", "trend_context"),
        ("Notes", "data_notes"),
    ):
        sentence = _summary_sentence(structured.get(key))
        if not sentence:
            continue
        rows.append(f"<div><strong>{label}</strong> {escape(sentence)}</div>")
    return "\n".join(rows) if rows else "Parcel summary unavailable."


def _parse_tax_ai_structured(raw_text: str) -> Optional[Dict[str, Optional[str]]]:
    try:
        data = json.loads(raw_text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    output: Dict[str, Optional[str]] = {}
    for key in (
        "parcel",
        "tax_position",
        "county_context",
        "neighborhood_context",
        "trend_context",
        "data_notes",
    ):
        value = data.get(key)
        if value is None:
            output[key] = None
        elif isinstance(value, str):
            output[key] = value.strip()
        else:
            output[key] = str(value).strip()
    return output


def _build_tax_ai_prompt(payload: Dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return (
        "You are a local property tax explainer. Use only the provided JSON payload.\n"
        "Return STRICT JSON with these keys ONLY:\n"
        "  parcel, tax_position, county_context, neighborhood_context, trend_context, data_notes\n"
        "Each value must be a single sentence (<= 220 chars) or null.\n"
        "No HTML, no markdown, no lists, no extra keys. Objective, factual, calculated.\n"
        "Parcel: address + parcel id + tax year + market value.\n"
        "Tax position: latest tax amount + effective tax rate (define once).\n"
        "County context: county median ETR + delta vs parcel (bps or percent).\n"
        "Neighborhood context: neighborhood name/code + percentile rank + peer count; include COD/PRD if present.\n"
        "Trend context: cumulative taxes + span years + tax CAGR vs inflation (pp spread).\n"
        "If data is missing, say it is unavailable in data_notes.\n\n"
        "Payload JSON (read-only):\n"
        f"{payload_json}\n"
    )


def _tax_ai_in_progress_key(parcel_id: str) -> str:
    return f"openskagit:tax-ai-summary:{parcel_id}:in-progress"


def _read_cached_tax_ai_summary(record: ParcelHistory, tax_fingerprint: str) -> Optional[Dict[str, Any]]:
    taxes_payload = _coerce_dict(record.taxes)
    cached_payload = taxes_payload.get(TAX_AI_SUMMARY_KEY)
    if not isinstance(cached_payload, dict):
        return None
    if cached_payload.get("tax_fingerprint") != tax_fingerprint:
        return None
    status = cached_payload.get("status", "ok")
    if status == "failed":
        return {
            "parcel_id": record.parcel_number,
            "tax_year": cached_payload.get("tax_year"),
            "status": "failed",
            "error": cached_payload.get("error"),
            "failed_at_ts": cached_payload.get("failed_at_ts"),
            "generated_at": cached_payload.get("generated_at"),
            "cached": True,
            "source": "parcel_tax_ai_summary",
        }
    if cached_payload.get("summary_html"):
        return {
            "parcel_id": record.parcel_number,
            "tax_year": cached_payload.get("tax_year"),
            "summary_html": cached_payload.get("summary_html"),
            "summary_text": cached_payload.get("summary_text"),
            "generated_at": cached_payload.get("generated_at"),
            "cached": True,
            "source": "parcel_tax_ai_summary",
            "status": "ok",
        }
    return None


def get_cached_parcel_tax_ai_summary(parcel_id: str) -> Optional[Dict[str, Any]]:
    record = (
        ParcelHistory.objects.filter(parcel_number=parcel_id)
        .only("rows", "taxes")
        .first()
    )
    if not record:
        return None
    tax_fingerprint = _history_fingerprint(record.rows, parcel_id)
    if not tax_fingerprint:
        return None
    return _read_cached_tax_ai_summary(record, tax_fingerprint)


def _store_tax_ai_failure(record: ParcelHistory, tax_fingerprint: str, error: str) -> Dict[str, Any]:
    taxes_payload = _coerce_dict(record.taxes)
    generated_at = timezone.now().isoformat()
    failed_at_ts = timezone.now().timestamp()
    taxes_payload[TAX_AI_SUMMARY_KEY] = {
        "status": "failed",
        "error": error,
        "tax_fingerprint": tax_fingerprint,
        "generated_at": generated_at,
        "failed_at_ts": failed_at_ts,
    }
    record.taxes = taxes_payload
    record.save(update_fields=["taxes"])
    return {
        "parcel_id": record.parcel_number,
        "status": "failed",
        "error": error,
        "failed_at_ts": failed_at_ts,
        "generated_at": generated_at,
        "cached": True,
        "source": "parcel_tax_ai_summary",
    }


def _build_parcel_tax_ai_summary(parcel_id: str) -> Optional[Dict[str, Any]]:
    record = (
        ParcelHistory.objects.filter(parcel_number=parcel_id)
        .only("rows", "taxes")
        .first()
    )
    if not record:
        return None

    tax_fingerprint = _history_fingerprint(record.rows, parcel_id)
    if not tax_fingerprint:
        return None

    cached = _read_cached_tax_ai_summary(record, tax_fingerprint)
    if cached and cached.get("status") != "failed":
        return cached

    payload = build_tax_ai_payload(parcel_id)
    if not payload:
        return None

    prompt = _build_tax_ai_prompt(payload)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    try:
        client = llm.get_openai_client()
        response = client.responses.create(
            model=TAX_AI_MODEL_NAME,
            input=prompt,
        )
    except Exception as exc:
        return _store_tax_ai_failure(record, tax_fingerprint, str(exc))

    raw_text = getattr(response, "output_text", "") or ""
    structured = _parse_tax_ai_structured(raw_text)
    if structured:
        summary_html = _render_tax_ai_summary(structured)
    else:
        summary_html = _sanitize_ai_summary_html(raw_text)
    summary_text = " ".join(strip_tags(summary_html).split())

    tax_year = None
    story_years = payload.get("tax_story", {}).get("history_years") if payload else None
    if isinstance(story_years, dict):
        tax_year = story_years.get("end")
    if tax_year is None and payload.get("tax_fairness"):
        tax_year = payload["tax_fairness"].get("tax_year")

    payload_hash = _payload_hash(payload)
    generated_at = timezone.now().isoformat()
    taxes_payload = _coerce_dict(record.taxes)
    taxes_payload[TAX_AI_SUMMARY_KEY] = {
        "status": "ok",
        "summary_html": summary_html,
        "summary_text": summary_text,
        "tax_year": tax_year,
        "tax_fingerprint": tax_fingerprint,
        "payload_hash": payload_hash,
        "prompt_version": TAX_AI_PROMPT_VERSION,
        "prompt_hash": prompt_hash,
        "model": TAX_AI_MODEL_NAME,
        "input_payload": payload,
        "structured_summary": structured,
        "generated_at": generated_at,
    }

    record.taxes = taxes_payload
    record.save(update_fields=["taxes"])

    return {
        "parcel_id": parcel_id,
        "tax_year": tax_year,
        "summary_html": summary_html,
        "summary_text": summary_text,
        "generated_at": generated_at,
        "cached": False,
        "source": "parcel_tax_ai_summary",
        "status": "ok",
    }


def enqueue_parcel_tax_ai_summary(parcel_id: str) -> bool:
    cache_key = _tax_ai_in_progress_key(parcel_id)
    if not cache.add(cache_key, True, TAX_AI_IN_PROGRESS_TTL):
        return False

    def _runner():
        close_old_connections()
        try:
            _build_parcel_tax_ai_summary(parcel_id)
        finally:
            cache.delete(cache_key)
            close_old_connections()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return True


def get_parcel_tax_ai_summary(parcel_id: str) -> Optional[Dict[str, Any]]:
    cached = get_cached_parcel_tax_ai_summary(parcel_id)
    if cached:
        return cached
    return _build_parcel_tax_ai_summary(parcel_id)
