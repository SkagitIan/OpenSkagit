import copy
import datetime as dt
import functools
import json
import logging
import math
import os
import operator
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db import connection
from django.db.models import Avg, Count, Max, Min, OuterRef, Q, Subquery
from django.db.models.functions import Upper
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_GET, require_POST


logger = logging.getLogger(__name__)

from . import adjustment_engine, appeals, cma, chat as chat_service, llm
from .models import (
    Assessor,
    CmaAnalysis,
    CmaComparableSelection,
    NeighborhoodGeom,
    NeighborhoodMetrics,
    NeighborhoodTrend,
    Parcel,
    ParcelHistory,
)
from .improvement_utils import QUALITY_WEIGHTS
from .valuation_areas import resolve_market_group


CMA_SESSION_KEY = "cma_state"
CMA_ALLOWED_SORT_FIELDS = {
    "distance",
    "sale_price",
    "sale_date",
    "adjusted_price",  # legacy alias; treated as sale_price
    "score",
}
CMA_ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}

CONDITION_SCORE_MAP = {
    "P": 1,
    "POOR": 1,
    "F": 2,
    "FAIR": 2,
    "A": 3,
    "AVERAGE": 3,
    "G": 4,
    "GOOD": 4,
    "VG": 5,
    "VERY GOOD": 5,
    "E": 6,
    "EXCELLENT": 6,
}

QUALITY_LABEL_SCORE_MAP = {
    "low": 1,
    "fair": 2,
    "average": 3,
    "good": 4,
    "very good": 5,
    "excellent": 6,
}

ADJUSTMENT_LABELS = [
    ("area", "Living area"),
    ("lot", "Lot size"),
    ("age", "Age"),
    ("quality", "Quality"),
    ("condition", "Condition"),
    ("garage", "Garage"),
    ("basement", "Basement"),
    ("view", "View"),
    ("time", "Time trend"),
]

ADJUSTMENT_TOOLTIP_METADATA = {
    "area": {"unit": "sq ft", "decimals": 0},
    "lot": {"unit": "acres", "decimals": 2},
    "age": {"unit": "years", "decimals": 1},
    "quality": {"unit": "pts", "decimals": 1},
    "condition": {"unit": "pts", "decimals": 1},
    "garage": {"unit": None, "decimals": 0},
    "basement": {"unit": None, "decimals": 0},
    "view": {"unit": None, "decimals": 0},
    "time": {"unit": "months", "decimals": 1},
}

ADJUSTMENT_STORYBOARD_CONFIG = {
    "size": {
        "label": "Size adjustments",
        "components": ("area", "lot"),
        "formula": "subject_pred_price × (exp(coef × Δlog(size)) - 1)",
    },
    "quality": {
        "label": "Quality adjustments",
        "components": ("quality",),
        "formula": "subject_pred_price × (exp(coef × Δquality_score) - 1)",
    },
    "condition": {
        "label": "Condition adjustments",
        "components": ("condition",),
        "formula": "subject_pred_price × (exp(coef × Δcondition_score) - 1)",
    },
    "time": {
        "label": "Time adjustments",
        "components": ("time",),
        "formula": "sale_price × (exp(beta_t × Δmonths) - 1)",
    },
    "location": {
        "label": "Location adjustments",
        "components": ("view",),
        "formula": "subject_pred_price × (exp(coef × Δview_flag) - 1)",
    },
}

ADJUSTMENT_STORYBOARD_ORDER = ["size", "quality", "condition", "time", "location"]

PARCEL_HISTORY_LIMIT = 24


def _log_comparables_step(parcel_number: str, step: str, elapsed: float, **metadata: object) -> None:
    details = " ".join(
        f"{key}={value}" for key, value in metadata.items() if value is not None
    )
    message = f"[comparables] parcel={parcel_number} step={step} took {elapsed:.3f}s"
    if details:
        message = f"{message} {details}"
    logger.info(message)


def _centroid_lat_lon(geom) -> Tuple[Optional[float], Optional[float]]:
    """
    Derive a representative latitude/longitude pair from a parcel geometry.
    Fall back to the geometry's own x/y when no centroid is available.
    """
    if geom is None:
        return None, None
    centroid = getattr(geom, "centroid", None)
    if centroid is not None:
        return getattr(centroid, "y", None), getattr(centroid, "x", None)
    return getattr(geom, "y", None), getattr(geom, "x", None)


def _get_cma_root_state(request) -> Dict[str, Any]:
    state = request.session.get(CMA_SESSION_KEY)
    if not isinstance(state, dict):
        state = {}
        request.session[CMA_SESSION_KEY] = state
        request.session.modified = True
    return state


def _get_parcel_state(request, parcel_number: str) -> Dict[str, Any]:
    state = _get_cma_root_state(request)
    parcel_state = state.get(parcel_number)
    if not isinstance(parcel_state, dict):
        parcel_state = {
            "excluded": [],
            "sort_field": "score",
            "sort_direction": "desc",
        }
        state[parcel_number] = parcel_state
        request.session.modified = True
    return parcel_state


def _toggle_comparable_inclusion(request, parcel_number: str, comp_parcel: str) -> bool:
    parcel_state = _get_parcel_state(request, parcel_number)
    excluded = parcel_state.setdefault("excluded", [])
    if comp_parcel in excluded:
        excluded.remove(comp_parcel)
        request.session.modified = True
        return True
    excluded.append(comp_parcel)
    request.session.modified = True
    return False


def _current_sort(
    request, parcel_state: Dict[str, Any], requested_field: Optional[str], requested_direction: Optional[str]
):
    field = requested_field or parcel_state.get("sort_field") or "score"
    direction = requested_direction or parcel_state.get("sort_direction") or "desc"
    if field not in CMA_ALLOWED_SORT_FIELDS:
        field = "score"
    if direction not in CMA_ALLOWED_SORT_DIRECTIONS:
        direction = "desc"
    if parcel_state.get("sort_field") != field or parcel_state.get("sort_direction") != direction:
        parcel_state["sort_field"] = field
        parcel_state["sort_direction"] = direction
        request.session.modified = True
    return field, direction


def _parse_limit(raw_limit: Optional[str]) -> int:
    try:
        limit = int(raw_limit) if raw_limit is not None else cma.DEFAULT_COMPARABLE_LIMIT
    except (TypeError, ValueError):
        limit = cma.DEFAULT_COMPARABLE_LIMIT
    limit = max(6, limit)
    return min(limit, cma.MAX_COMPARABLE_LIMIT)


def _parse_currency_value(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parcel_value_history(parcel_number: str, limit: int = PARCEL_HISTORY_LIMIT) -> List[Dict[str, Any]]:
    if not parcel_number:
        return []
    record = ParcelHistory.objects.only("rows").filter(parcel_number=parcel_number).first()
    if not record:
        return []
    raw_rows = record.rows or []
    entries: List[Dict[str, Any]] = []
    for row in raw_rows:
        year_text = row.get("VALUE YEAR") or row.get("TAX YEAR")
        try:
            year = int(year_text)
        except (TypeError, ValueError):
            continue
        value = None
        for key in ("MARKET TOTAL", "LAND MARKET", "ASSESSED TOTAL", "LAND ASSESSED"):
            value = _parse_currency_value(row.get(key))
            if value is not None:
                break
        if value is None:
            continue
        entries.append({"year": year, "value": value})
    if not entries:
        return []
    entries.sort(key=lambda item: item["year"])
    if len(entries) > limit:
        entries = entries[-limit:]
    return entries


def _safe_float_value(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_similarity(primary: Optional[float], secondary: Optional[float]) -> Optional[float]:
    if primary is None or secondary is None:
        return None
    if primary <= 0 or secondary <= 0:
        return None
    ratio = min(primary, secondary) / max(primary, secondary)
    return max(0.0, min(1.0, ratio))


def _match_text_score(subject_value: Any, comparable_value: Any) -> Optional[float]:
    if subject_value in (None, "", "null") or comparable_value in (None, "", "null"):
        return None
    subject_text = str(subject_value).strip().lower()
    comparable_text = str(comparable_value).strip().lower()
    if not subject_text or not comparable_text:
        return None
    return 1.0 if subject_text == comparable_text else 0.6


def _average_score(values: List[Optional[float]]) -> Optional[float]:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _percentage_score(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    percentage = round(value * 100)
    return max(0, min(100, percentage))


def _merge_request_params(request) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, value in request.GET.items():
        merged[key] = value
    if request.method == "POST":
        for key, value in request.POST.items():
            merged[key] = value
    return merged


def _metadata_dict(snapshot: cma.PropertySnapshot) -> Dict[str, Any]:
    metadata = snapshot.metadata
    if not isinstance(metadata, dict):
        return {}
    return metadata


def _quality_score(metadata: Dict[str, Any]) -> Optional[float]:
    improvements = metadata.get("improvements")
    if isinstance(improvements, dict):
        code = (improvements.get("quality_code") or "").strip().upper()
        if code:
            score = QUALITY_WEIGHTS.get(code)
            if score:
                return float(score)
        label = improvements.get("quality")
        if isinstance(label, str):
            score = QUALITY_LABEL_SCORE_MAP.get(label.strip().lower())
            if score:
                return float(score)
    raw = metadata.get("quality_score")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _condition_score(metadata: Dict[str, Any]) -> Optional[float]:
    improvements = metadata.get("improvements")
    code = None
    if isinstance(improvements, dict):
        code = improvements.get("condition_code")
    if not code:
        code = metadata.get("condition_code")
    if isinstance(code, str):
        normalized = code.strip().upper()
        score = CONDITION_SCORE_MAP.get(normalized)
        if score:
            return float(score)
    label = None
    if isinstance(improvements, dict):
        label = improvements.get("condition")
    if isinstance(label, str):
        score = CONDITION_SCORE_MAP.get(label.strip().upper())
        if score:
            return float(score)
    raw = metadata.get("condition_score")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _boolean_flag(value: Any) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 0:
        return 1
    if numeric == 0:
        return 0
    return None


def _calculate_age(snapshot: cma.PropertySnapshot, reference_date: Optional[dt.date]) -> Optional[float]:
    year = snapshot.year_built or snapshot.effective_year_built
    if not year:
        return None
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return None
    if reference_date is None:
        reference_date = timezone.now().date()
    return max(reference_date.year - year_int, 0)


def _subject_predicted_price(subject: cma.PropertySnapshot, market_group: Optional[str]) -> Optional[float]:
    metadata = _metadata_dict(subject)
    candidate_keys = (
        "predicted_value",
        "subject_pred_price",
        "regression_predicted_value",
        "regression_market_value",
        "model_price",
    )
    for key in candidate_keys:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    if subject.assessed_value is not None:
        try:
            return float(subject.assessed_value)
        except (TypeError, ValueError):
            pass
    if subject.sale_price is not None:
        try:
            return float(subject.sale_price)
        except (TypeError, ValueError):
            pass
    if market_group:
        payload = _snapshot_adjustment_payload(subject, market_group=market_group)
        predicted = adjustment_engine.predict_price(payload, market_group=market_group)
        if predicted is not None:
            return predicted
    return None


def _subject_market_group(subject: cma.PropertySnapshot) -> Optional[str]:
    metadata = _metadata_dict(subject)
    candidates = (
        metadata.get("valuation_area"),
        metadata.get("market_group"),
        metadata.get("city_district"),
    )
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate).strip()
        if text:
            return text.upper()
    mapped = resolve_market_group(metadata.get("neighborhood_code"))
    if mapped:
        return mapped
    return None


def _has_basement(metadata: Dict[str, Any]) -> Optional[int]:
    if "has_basement" in metadata:
        return _boolean_flag(metadata.get("has_basement"))
    finished = metadata.get("finished_basement_sqft")
    unfinished = metadata.get("unfinished_basement_sqft")
    if finished not in (None, "", 0) or unfinished not in (None, "", 0):
        return 1
    return None


def _snapshot_adjustment_payload(
    snapshot: cma.PropertySnapshot,
    *,
    market_group: Optional[str] = None,
    include_sale_price: bool = False,
) -> Dict[str, Any]:
    metadata = _metadata_dict(snapshot)
    sale_date = snapshot.sale_date.isoformat() if snapshot.sale_date else None
    lot_acres_val: Optional[float] = None
    if snapshot.lot_acres is not None:
        try:
            lot_acres_val = float(snapshot.lot_acres)
        except (TypeError, ValueError):
            lot_acres_val = None
    if lot_acres_val is None:
        raw_lot = metadata.get("lot_acres")
        try:
            lot_acres_val = float(raw_lot) if raw_lot is not None else None
        except (TypeError, ValueError):
            lot_acres_val = None

    age_val = metadata.get("age")
    if age_val is None:
        age_val = _calculate_age(snapshot, snapshot.sale_date)

    has_garage_val = metadata.get("has_garage")
    if has_garage_val is None:
        has_garage_val = _boolean_flag(snapshot.garage_sqft)

    payload = {
        "GLA": float(snapshot.living_area) if snapshot.living_area is not None else None,
        "lot_acres": lot_acres_val,
        "age": age_val,
        "quality_score": _quality_score(metadata),
        "condition_score": _condition_score(metadata),
        "has_garage": has_garage_val,
        "has_basement": _has_basement(metadata),
        "is_view": _boolean_flag(metadata.get("has_view")),
        "sale_date": sale_date,
        "property_type": snapshot.property_type,
    }
    if market_group:
        payload["valuation_area"] = market_group
    if include_sale_price and snapshot.sale_price is not None:
        try:
            payload["sale_price"] = float(snapshot.sale_price)
        except (TypeError, ValueError):
            payload["sale_price"] = None
    return payload


def _comparable_adjustment_payload(comp: cma.ComparableResult) -> Optional[Dict[str, Any]]:
    snapshot = comp.snapshot
    base_payload = _snapshot_adjustment_payload(snapshot, include_sale_price=True)
    sale_price = base_payload.get("sale_price")
    if sale_price in (None, ""):
        return None
    base_payload["comp_id"] = snapshot.parcel_number
    return base_payload


def _format_measure_value(value: Any, decimals: int) -> Optional[str]:
    if value in (None, "", "null"):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    formatted = f"{numeric:,.{decimals}f}"
    if decimals == 0:
        formatted = formatted.split(".")[0]
    return formatted


def _signed_delta_text(delta: float, decimals: int) -> str:
    formatted = _format_measure_value(abs(delta), decimals)
    if formatted is None:
        formatted = f"{abs(delta):,.{decimals}f}"
        if decimals == 0:
            formatted = formatted.split(".")[0]
    if delta > 0:
        return f"+{formatted}"
    if delta < 0:
        return f"-{formatted}"
    return formatted


def _describe_numeric_delta(label: str, key: str, detail: Dict[str, Any]) -> str:
    config = ADJUSTMENT_TOOLTIP_METADATA.get(key, {})
    unit = config.get("unit")
    decimals = config.get("decimals", 0)
    delta = detail.get("delta")
    prefix = f"{label} difference"
    if delta is None:
        return f"{prefix} unavailable."
    if delta == 0:
        sentence = f"{prefix}: No difference detected."
    else:
        signed = _signed_delta_text(delta, decimals)
        direction = "Subject higher" if delta > 0 else "Comparable higher"
        sentence = (
            f"{prefix}: {signed}{f' {unit}' if unit else ''} ({direction})."
        )
    subject_value = _format_measure_value(detail.get("subject_value"), decimals)
    comp_value = _format_measure_value(detail.get("comp_value"), decimals)
    parts = []
    if subject_value:
        parts.append(f"Subject: {subject_value}{f' {unit}' if unit else ''}")
    if comp_value:
        parts.append(f"Comparable: {comp_value}{f' {unit}' if unit else ''}")
    if parts:
        sentence = f"{sentence} {'; '.join(parts)}"
    return sentence


def _describe_feature_delta(label: str, detail: Dict[str, Any]) -> str:
    subject_flag = detail.get("subject_value")
    comp_flag = detail.get("comp_value")
    if subject_flag is None and comp_flag is None:
        return f"{label} data unavailable."
    if subject_flag is not None and comp_flag is not None:
        subject_has = bool(subject_flag)
        comp_has = bool(comp_flag)
        if subject_has and not comp_has:
            return f"{label}: Subject has this feature while the comparable does not."
        if not subject_has and comp_has:
            return f"{label}: Comparable has this feature while the subject does not."
        if subject_has:
            return f"{label}: Both properties have this feature."
        return f"{label}: Neither property has this feature."
    if subject_flag is not None:
        return f"{label}: Subject {'has' if bool(subject_flag) else 'does not have'} this feature; comparable data missing."
    return f"{label}: Comparable {'has' if bool(comp_flag) else 'does not have'} this feature; subject data missing."


def _describe_time_delta(label: str, detail: Dict[str, Any]) -> str:
    prefix = f"{label} difference"
    stats = ADJUSTMENT_TOOLTIP_METADATA.get("time", {})
    decimals = stats.get("decimals", 1)
    unit = stats.get("unit", "months")
    delta = detail.get("delta")
    if delta is None:
        return f"{prefix} unavailable."
    signed = _signed_delta_text(delta, decimals)
    if delta > 0:
        direction = "Subject valuation date is later than the comparable sale."
    elif delta < 0:
        direction = "Subject valuation date is earlier than the comparable sale."
    else:
        direction = "Subject valuation date matches the comparable sale."
    sentence = f"{prefix}: {signed} {unit} ({direction})"
    subject_date = detail.get("subject_value")
    comp_date = detail.get("comp_value")
    dates = []
    if subject_date:
        dates.append(f"Subject: {subject_date}")
    if comp_date:
        dates.append(f"Comparable: {comp_date}")
    if dates:
        sentence = f"{sentence}. {'; '.join(dates)}"
    return sentence


def _adjustment_delta_description(
    key: str,
    label: str,
    detail: Optional[Dict[str, Any]],
) -> str:
    if not detail:
        return f"{label} difference unavailable."
    if key in {"garage", "basement", "view"}:
        return _describe_feature_delta(label, detail)
    if key == "time":
        return _describe_time_delta(label, detail)
    return _describe_numeric_delta(label, key, detail)


def _compute_adjustment_summary(
    subject: cma.PropertySnapshot,
    comparables: List[cma.ComparableResult],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    market_group = _subject_market_group(subject)
    if not market_group:
        return None, "Market/valuation group unavailable."
    subject_pred_price = _subject_predicted_price(subject, market_group)
    if subject_pred_price is None:
        return None, "Predicted subject price unavailable."
    comps_payload: List[Dict[str, Any]] = []
    for comp in comparables:
        payload = _comparable_adjustment_payload(comp)
        if payload:
            comps_payload.append(payload)
    if not comps_payload:
        return None, "Comparable sale pricing unavailable."
    subject_payload = _snapshot_adjustment_payload(subject, market_group=market_group)
    try:
        raw_payload = adjustment_engine.compute_adjustments(
            subject=subject_payload,
            comps=comps_payload,
            subject_pred_price=subject_pred_price,
            market_group=market_group,
        )
    except adjustment_engine.MissingCoefficientError as exc:
        return None, str(exc)
    except adjustment_engine.AdjustmentEngineError as exc:
        return None, str(exc)
    for comp in raw_payload.get("comparables", []):
        adjustments = comp.get("adjustments") or {}
        detail_list = []
        adjustment_details = comp.get("adjustment_details") or {}
        for key, label in ADJUSTMENT_LABELS:
            detail = adjustment_details.get(key)
            detail_list.append(
                {
                    "key": key,
                    "label": label,
                    "amount": adjustments.get(key, 0.0),
                    "delta_text": _adjustment_delta_description(key, label, detail),
                }
            )
        comp["adjustment_list"] = detail_list
    return raw_payload, None


def _load_neighborhood_sales_ratio_history(code: Optional[str], *, limit: int = 10) -> List[Dict[str, Any]]:
    if not code:
        return []
    normalized = str(code or "").strip()
    if not normalized:
        return []
    normalized_upper = normalized.upper()
    qs = (
        NeighborhoodMetrics.objects.filter(neighborhood_code__iexact=normalized_upper)
        .order_by("-year")
    )
    history = []
    for metric in qs[:limit]:
        history.append(
            {
                "year": metric.year,
                "sales_ratio": float(metric.sales_ratio) if metric.sales_ratio is not None else None,
                "median_ratio": float(metric.median_ratio) if metric.median_ratio is not None else None,
            }
        )
    return sorted(history, key=lambda item: item["year"])


def _prepare_adjustment_storyboard(
    adjustment_payload: Dict[str, Any],
    subject: cma.PropertySnapshot,
    comparables: List[cma.ComparableResult],
) -> List[Dict[str, Any]]:
    story_items: List[Dict[str, Any]] = []
    market_group = _subject_market_group(subject)
    subject_payload = _snapshot_adjustment_payload(subject, market_group=market_group)
    comp_payloads: List[Dict[str, Any]] = []
    for comp in comparables:
        snapshot = getattr(comp, "snapshot", None)
        if not isinstance(snapshot, cma.PropertySnapshot):
            continue
        comp_payloads.append(_snapshot_adjustment_payload(snapshot))
    comp_count = len(comp_payloads)
    if comp_count == 0:
        return story_items

    def _average(field: str) -> Optional[float]:
        values = []
        for payload in comp_payloads:
            value = payload.get(field)
            if value in (None, "", "null"):
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not values:
            return None
        return sum(values) / len(values)

    def _format_sqft(value: Optional[float]) -> str:
        if value is None:
            return "data unavailable"
        try:
            rounded = int(round(value))
            return f"{rounded:,} sq ft"
        except Exception:
            return "data unavailable"

    def _format_acres(value: Optional[float]) -> str:
        if value is None:
            return "data unavailable"
        try:
            return f"{value:.2f} acres"
        except Exception:
            return "data unavailable"

    def _format_score(value: Optional[float]) -> str:
        if value is None:
            return "unreported"
        try:
            return f"{value:.1f}"
        except Exception:
            return "unreported"

    def _parse_date(value: Optional[str]) -> Optional[dt.date]:
        if not value:
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            try:
                return dt.date.fromisoformat(value.split("T")[0])
            except Exception:
                return None

    subject_area_text = _format_sqft(subject_payload.get("GLA"))
    subject_lot_text = _format_acres(subject_payload.get("lot_acres"))
    subject_quality_text = _format_score(subject_payload.get("quality_score"))
    subject_condition_text = _format_score(subject_payload.get("condition_score"))
    subject_view_flag = subject_payload.get("is_view")
    subject_view_text = (
        "has a view"
        if subject_view_flag == 1
        else "does not have a view"
        if subject_view_flag == 0
        else "view data unavailable"
    )

    comp_area_text = _format_sqft(_average("GLA"))
    comp_lot_text = _format_acres(_average("lot_acres"))
    comp_quality_text = _format_score(_average("quality_score"))
    comp_condition_text = _format_score(_average("condition_score"))

    view_flags = [payload.get("is_view") for payload in comp_payloads if payload.get("is_view") in (0, 1)]
    comp_view_percent = None
    if view_flags:
        comp_view_percent = (sum(view_flags) / len(view_flags)) * 100
    comp_view_text = (
        f"{round(comp_view_percent)}% of comparables" if comp_view_percent is not None else "view data unavailable"
    )

    subject_sale_date = _parse_date(subject_payload.get("sale_date"))
    if subject_sale_date:
        subject_date_text = subject_sale_date.strftime("%b %Y")
    else:
        subject_date_text = "valuation date"

    comp_sale_dates = sorted(
        [d for d in (_parse_date(payload.get("sale_date")) for payload in comp_payloads) if d is not None]
    )
    if comp_sale_dates:
        start = comp_sale_dates[0].strftime("%b %Y")
        end = comp_sale_dates[-1].strftime("%b %Y")
        sale_range_text = start if start == end else f"{start} – {end}"
    else:
        sale_range_text = "sale dates unavailable"

    detail_lines: Dict[str, List[str]] = {
        "size": [
            ADJUSTMENT_STORYBOARD_CONFIG["size"]["formula"],
            f"Source: Your home is {subject_area_text} on {subject_lot_text}; comparables average {comp_area_text} on {comp_lot_text}.",
        ],
        "quality": [
            ADJUSTMENT_STORYBOARD_CONFIG["quality"]["formula"],
            f"Source: Your quality score is {subject_quality_text} vs comparables averaging {comp_quality_text}.",
        ],
        "condition": [
            ADJUSTMENT_STORYBOARD_CONFIG["condition"]["formula"],
            f"Source: Your condition score is {subject_condition_text} vs comparables averaging {comp_condition_text}.",
        ],
        "time": [
            ADJUSTMENT_STORYBOARD_CONFIG["time"]["formula"],
            f"Source: Comps sold between {sale_range_text} trended to {subject_date_text}.",
        ],
        "location": [
            ADJUSTMENT_STORYBOARD_CONFIG["location"]["formula"],
            f"Source: Your property {subject_view_text}; {comp_view_text} reported the same view flag.",
        ],
    }

    for story_id in ADJUSTMENT_STORYBOARD_ORDER:
        config = ADJUSTMENT_STORYBOARD_CONFIG.get(story_id)
        if not config:
            continue
        amounts: List[float] = []
        for comp in adjustment_payload.get("comparables", []):
            total = 0.0
            for entry in comp.get("adjustment_list", []):
                if entry.get("key") in config["components"]:
                    amount = entry.get("amount")
                    if isinstance(amount, (int, float)):
                        total += float(amount)
            amounts.append(total)
        if not amounts:
            continue
        avg_amount = sum(amounts) / len(amounts)
        story_items.append(
            {
                "id": story_id,
                "label": config["label"],
                "amount": avg_amount,
                "details": detail_lines.get(story_id, []),
            }
        )
    return story_items


API_ENDPOINTS = [
    {
        "key": "parcel-detail",
        "name": "Parcel Detail",
        "method": "GET",
        "path": "/api/parcel/{parcel_number}/",
        "description": "Retrieve parcel details joined across assessor, land, improvements, and sales data.",
        "instructions": "Type in a parcel number when you need the full story for one property. The reply bundles values, building facts, land, and the five most recent verified sales so a teammate can speak to the parcel with confidence.",
        "use_case": "Show a rich fact sheet when someone clicks a parcel pin or a row in search results.",
        "parameters": [
            {
                "name": "parcel_number",
                "location": "path",
                "type": "string",
                "required": True,
                "description": "11-character parcel number such as P12345.",
            }
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/parcel/P12345/",
                "query": {},
            },
            indent=2,
        ),
        "sample": {
            "parcel_number": "P12345",
            "address": "101 Main St",
            "valuation": {"assessed": 475000, "market": 512000, "taxable": 460000},
            "structure": {"bedrooms": 3, "bathrooms": 2, "living_area_sqft": 1820, "year_built": 1997},
            "districts": {"city": "Mount Vernon", "school": "SD201", "fire": "F01"},
            "location": {"latitude": 48.42, "longitude": -122.31, "acres": 0.22},
            "land": {
                "total_acres": 0.22,
                "total_market_value": 120000,
                "segments": [{"land_type": "RESIDENTIAL", "market_value": 120000}],
            },
            "improvements": [{"improvement_id": 1, "description": "Single family residence", "improvement_value": 355000}],
            "sales": {
                "latest": {"sale_price": 450000, "sale_date": "2021-04-02"},
                "recent_valid": [{"sale_price": 450000, "sale_date": "2021-04-02"}],
                "total_records": 6,
            },
        },
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "sales-list",
        "name": "Sales Leaderboard",
        "method": "GET",
        "path": "/api/sales/",
        "description": "Return top valid sales with assessor, land, and improvement context. Override sort direction via `direction=asc|desc`.",
        "instructions": "Use this feed when you want to call out headline sales. Pick a sort option, tighten the filters (price, neighborhood, acreage), and the service will hand back the most noteworthy transfers first.",
        "use_case": "Populate a “Recent Movers” card on a dashboard or a report that highlights high-dollar closings.",
        "parameters": [
            {"name": "limit", "location": "query", "type": "int", "required": False, "description": "Default 25, max 100."},
            {"name": "sort", "location": "query", "type": "string", "required": False, "description": "One of recent, sale_price, neighborhood, assessed_value, market_value, acres, year_built."},
            {"name": "direction", "location": "query", "type": "string", "required": False, "description": "asc or desc. Defaults to the sort's natural direction."},
            {"name": "neighborhood", "location": "query", "type": "string", "required": False, "description": "Exact neighborhood code filter."},
            {"name": "city", "location": "query", "type": "string", "required": False, "description": "City district filter."},
            {"name": "parcel_number", "location": "query", "type": "string", "required": False, "description": "Restrict to a single parcel number."},
            {"name": "min_sale_price", "location": "query", "type": "number", "required": False, "description": "Lower sale price bound."},
            {"name": "max_sale_price", "location": "query", "type": "number", "required": False, "description": "Upper sale price bound."},
            {"name": "start_date", "location": "query", "type": "ISO datetime", "required": False, "description": "Earliest sale_date to include."},
            {"name": "end_date", "location": "query", "type": "ISO datetime", "required": False, "description": "Latest sale_date to include."},
            {"name": "land_use_code", "location": "query", "type": "string", "required": False, "description": "Match a land use code."},
            {"name": "property_type", "location": "query", "type": "string", "required": False, "description": "Restrict to one assessor property type."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "Lower acreage bound."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "Upper acreage bound."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/sales/",
                "query": {
                    "sort": "sale_price",
                    "direction": "desc",
                    "limit": 5,
                    "min_sale_price": 450000,
                },
            },
            indent=2,
        ),
        "sample": {
            "count": 125,
            "limit": 10,
            "sort": {"field": "sale_price", "direction": "desc"},
            "results": [
                {
                    "parcel_number": "P67890",
                    "sale": {
                        "sale_id": 98765,
                        "account_number": "ACCT-12345",
                        "seller_name": "Doe Family Trust",
                        "buyer_name": "Skagit Holdings LLC",
                        "sale_price": 735000,
                        "sale_date": "2023-09-15T00:00:00",
                        "sale_type": "valid sale",
                        "recording_number": "2023-0901-1234",
                        "deed_type": "Warranty Deed",
                        "deed_date": "2023-09-10T00:00:00",
                        "revaluation_area": 12.0,
                        "excise_number": 456789.0,
                    },
                    "parcel": {
                        "address": "456 River Rd",
                        "neighborhood_code": "NE45",
                        "land_use_code": "11",
                        "property_type": "Single Family",
                        "city_district": "Mount Vernon",
                        "school_district": "SD201",
                        "fire_district": "F01",
                        "assessed_value": 690000,
                        "market_value": 710000,
                        "taxable_value": 685000,
                        "acres": 0.38,
                        "year_built": 2018,
                        "effective_year_built": 2019,
                        "bedrooms": 4,
                        "bathrooms": 3,
                        "living_area": 2650,
                    },
                    "land": {
                        "total_acres": 0.38,
                        "total_market_value": 210000,
                        "segments": [
                            {
                                "property_value_year": 2023,
                                "land_type": "RESIDENTIAL",
                                "size_acres": 0.38,
                                "size_square_feet": 16552,
                                "market_value": 210000,
                                "market_unit_price": 552000,
                                "land_segment_comment": "Cul-de-sac",
                            }
                        ],
                    },
                    "improvements": [
                        {
                            "improvement_id": 1,
                            "description": "Residence",
                            "building_style": "Two Story",
                            "condition_code": "Good",
                            "improvement_value": 500000,
                            "total_living_area": 2650,
                            "actual_year_built": 2018,
                            "effective_year_built": 2019,
                        }
                    ],
                }
            ],
        },
        "default_path_params": {},
        "default_querystring": "sort=sale_price&direction=desc&limit=10",
        "default_body": "",
    },
    {
        "key": "parcel-search",
        "name": "Parcel Search",
        "method": "GET",
        "path": "/api/search/",
        "description": "Filter parcels with pagination and value, year, sale price, and acreage constraints.",
        "instructions": "Lean on this search whenever someone is trying to browse for property. Mix-and-match address text, parcel IDs, pricing, acreage, and year built filters, then turn the page controls to keep scrolling.",
        "use_case": "Power the main search results grid or a “find similar homes” drawer with pagination.",
        "parameters": [
            {"name": "page", "location": "query", "type": "int", "required": False, "description": "1-based page index; defaults to 1."},
            {"name": "page_size", "location": "query", "type": "int", "required": False, "description": "Defaults to REST_FRAMEWORK PAGE_SIZE (25) and max 250."},
            {"name": "address", "location": "query", "type": "string", "required": False, "description": "Case-insensitive contains search."},
            {"name": "parcel_number", "location": "query", "type": "string", "required": False, "description": "Exact parcel number."},
            {"name": "min_value", "location": "query", "type": "number", "required": False, "description": "Minimum assessed value."},
            {"name": "max_value", "location": "query", "type": "number", "required": False, "description": "Maximum assessed value."},
            {"name": "district", "location": "query", "type": "string", "required": False, "description": "City district filter."},
            {"name": "min_year", "location": "query", "type": "int", "required": False, "description": "Oldest acceptable year_built."},
            {"name": "max_year", "location": "query", "type": "int", "required": False, "description": "Newest acceptable year_built."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "Minimum acreage filter."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "Maximum acreage filter."},
            {"name": "min_sale_price", "location": "query", "type": "number", "required": False, "description": "Minimum last sale price (if a sale exists)."},
            {"name": "max_sale_price", "location": "query", "type": "number", "required": False, "description": "Maximum last sale price (if a sale exists)."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/search/",
                "query": {
                    "address": "Main St",
                    "min_value": 350000,
                    "max_value": 750000,
                    "page": 1,
                    "page_size": 25,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "address=Main St&min_value=300000&max_value=700000",
        "default_body": "",
    },
    {
        "key": "parcel-summary",
        "name": "Parcel Summary",
        "method": "GET",
        "path": "/api/summary/",
        "description": "Aggregate parcel metrics suitable for dashboards and reporting.",
        "instructions": "Reach for this rollup when you want quick talking points: pick a grouping (city, school, fire, neighborhood, levy) and let the service total or average the values.",
        "use_case": "Build KPI cards like “Average assessed value by city” or “Top 10 neighborhoods by acreage value.”",
        "parameters": [
            {"name": "group_by", "location": "query", "type": "string", "required": True, "description": "Required. One of city_district, school_district, fire_district, neighborhood_code, levy_code."},
            {"name": "metric", "location": "query", "type": "string", "required": True, "description": "Required. One of avg_assessed_value, avg_market_value, total_assessed_value, parcel_count."},
            {"name": "limit", "location": "query", "type": "int", "required": False, "description": "Number of rows to return (default 50, max 200)."},
            {"name": "address", "location": "query", "type": "string", "required": False, "description": "Optional filter identical to /api/search."},
            {"name": "parcel_number", "location": "query", "type": "string", "required": False, "description": "Optional filter identical to /api/search."},
            {"name": "min_value", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "max_value", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "district", "location": "query", "type": "string", "required": False, "description": "See /api/search filters."},
            {"name": "min_year", "location": "query", "type": "int", "required": False, "description": "See /api/search filters."},
            {"name": "max_year", "location": "query", "type": "int", "required": False, "description": "See /api/search filters."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "min_sale_price", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
            {"name": "max_sale_price", "location": "query", "type": "number", "required": False, "description": "See /api/search filters."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/summary/",
                "query": {
                    "group_by": "city_district",
                    "metric": "avg_assessed_value",
                    "limit": 10,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "group_by=city_district&metric=avg_assessed_value",
        "default_body": "",
    },
    {
        "key": "semantic-search",
        "name": "Semantic Search",
        "method": "POST",
        "path": "/api/semantic_search/",
        "description": "Vector similarity search against parcel embeddings using MiniLM and pgvector.",
        "instructions": "Let teammates describe the dream property in plain language (for example “farmhouse with mountain view and 5 acres”). The service scores every embedding and returns the closest matches, or a reasonable fallback list if vectors are offline.",
        "use_case": "Offer a natural-language search box that surfaces “homes like this” suggestions.",
        "parameters": [
            {"name": "query", "location": "body", "type": "string", "required": True, "description": "Natural language description to embed."},
            {"name": "limit", "location": "body", "type": "int", "required": False, "description": "Max matches to return (default 10, max 50)."},
        ],
        "request_example": json.dumps(
            {
                "method": "POST",
                "url": "/api/semantic_search/",
                "body": {
                    "query": "modern farmhouse with a big lot and room for a shop",
                    "limit": 8,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "",
        "default_body": json.dumps({"query": "modern farmhouse with large lot"}, indent=2),
    },
    {
        "key": "parcel-nearby",
        "name": "Nearby Parcels",
        "method": "GET",
        "path": "/api/nearby/",
        "description": "Find nearby parcels using PostGIS ST_DWithin with optional acreage and value filters.",
        "instructions": "Drop a pin (lat/lon) and a comfortable walking radius to see which parcels surround that point. Layer on assessed value or acreage limits to keep the list manageable.",
        "use_case": "Drive a “near me” sidebar when exploring a parcel on the map.",
        "parameters": [
            {"name": "lat", "location": "query", "type": "number", "required": True, "description": "Latitude of the search center."},
            {"name": "lon", "location": "query", "type": "number", "required": True, "description": "Longitude of the search center."},
            {"name": "radius", "location": "query", "type": "number", "required": False, "description": "Radius in meters (defaults to 1000). Alias: radius_meters."},
            {"name": "limit", "location": "query", "type": "int", "required": False, "description": "Max results (default 50, max 200)."},
            {"name": "min_value", "location": "query", "type": "number", "required": False, "description": "Minimum assessed value."},
            {"name": "max_value", "location": "query", "type": "number", "required": False, "description": "Maximum assessed value."},
            {"name": "min_acres", "location": "query", "type": "number", "required": False, "description": "Minimum acreage."},
            {"name": "max_acres", "location": "query", "type": "number", "required": False, "description": "Maximum acreage."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/nearby/",
                "query": {
                    "lat": 48.45,
                    "lon": -122.33,
                    "radius": 1500,
                    "min_value": 300000,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "lat=48.45&lon=-122.33&radius=2000",
        "default_body": "",
    },
    {
        "key": "neighborhood-stats",
        "name": "Neighborhood Stats",
        "method": "GET",
        "path": "/api/neighborhood_stats/{neighborhood_code}/",
        "description": "Return the latest snapshot for a neighborhood code (alias: /api/neighborhoods/{code}/).",
        "instructions": "Whenever a teammate wants quick neighborhood talking points, give them this snapshot. Provide the code (like NE045) and optionally the assessment year to pull the figures they care about.",
        "use_case": "Show a context card above parcel details describing the neighborhood’s average value and change rates.",
        "parameters": [
            {"name": "neighborhood_code", "location": "path", "type": "string", "required": True, "description": "Assessor neighborhood code, e.g. NE045."},
            {"name": "year", "location": "query", "type": "int", "required": False, "description": "Optional assessment year override."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/neighborhood_stats/NE045/",
                "query": {
                    "year": 2024,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"neighborhood_code": "NE045"},
        "default_querystring": "year=2024",
        "default_body": "",
    },
    {
        "key": "appeal-analysis",
        "name": "Appeal Analysis",
        "method": "GET",
        "path": "/api/appeal_analysis/{parcel_number}/",
        "description": "Return a heuristic appeal likelihood rating for a parcel.",
        "instructions": "Before inviting someone to file an appeal, run this health check. It returns a 0–100 score, a friendly rating, and why we think that rating fits so staff can offer helpful guidance.",
        "use_case": "Gate the “Start appeal” CTA with a quick recommendation and talking points.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Parcel to analyze."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeal_analysis/P12345/",
                "query": {},
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "appeal-search",
        "name": "Appeal Parcel Search",
        "method": "GET",
        "path": "/api/appeals/search/",
        "description": "Citizen-facing parcel/address search limited to residential property in the latest roll year.",
        "instructions": "Use this friendly search box as residents type their parcel or street. Once three characters have been entered, we return matching residential parcels from the active roll year.",
        "use_case": "Power the auto-complete field at the top of the appeal intake wizard.",
        "parameters": [
            {"name": "q", "location": "query", "type": "string", "required": True, "description": "Parcel number or address fragment (min length 3)."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/search/",
                "query": {
                    "q": "101 Main",
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {},
        "default_querystring": "q=101 Main St",
        "default_body": "",
    },
    {
        "key": "appeal-subject",
        "name": "Appeal Subject Snapshot",
        "method": "GET",
        "path": "/api/appeals/{parcel_number}/subject/",
        "description": "Roll-aware property snapshot plus neighborhood context for the appeal wizard.",
        "instructions": "After the resident picks their parcel, call this endpoint to fill the sidebar with their valuation, home facts, and neighborhood averages. It keeps everyone aligned on the same baseline data.",
        "use_case": "Pre-fill the appeal form with the subject parcel’s assessor facts.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Appeal subject parcel."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/P12345/subject/",
                "query": {},
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "appeal-comparables",
        "name": "Appeal Comparables",
        "method": "GET",
        "path": "/api/appeals/{parcel_number}/comparables/",
        "description": "Fetch cached comparable sales, appeal score, and soft-stop messages for a parcel.",
        "instructions": "Surface this data when a resident or staff member wants to review comps. You can ask for more comps by increasing the `count` value, and the response also shares why we think an appeal will or won’t succeed.",
        "use_case": "Fill the “Comparable Sales” tab in the appeal flow with ready-to-read cards.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Parcel requesting comparable set."},
            {"name": "count", "location": "query", "type": "int", "required": False, "description": "Target number of comparables. Defaults to the INITIAL_COMPARABLE_LIMIT and maxes at EXTENDED_COMPARABLE_LIMIT."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/P12345/comparables/",
                "query": {
                    "count": 7,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "count=7",
        "default_body": "",
    },
    {
        "key": "appeal-improvements",
        "name": "Comparable Improvements",
        "method": "GET",
        "path": "/api/appeals/{parcel_number}/comparables/{comp_parcel}/improvements/",
        "description": "Return improvement rollup details for a selected comparable parcel.",
        "instructions": "When someone expands a comparable card they usually want to see the nuts and bolts (square footage, style, year built). This endpoint hands those details back for the comparable you pass in.",
        "use_case": "Reveal the structure breakdown for a selected comp without loading the entire dataset again.",
        "parameters": [
            {"name": "parcel_number", "location": "path", "type": "string", "required": True, "description": "Appeal subject parcel."},
            {"name": "comp_parcel", "location": "path", "type": "string", "required": True, "description": "Comparable parcel id whose improvements are requested."},
            {"name": "roll_year", "location": "query", "type": "int", "required": False, "description": "Optional roll year override."},
            {"name": "roll_id", "location": "query", "type": "int", "required": False, "description": "Optional roll identifier override."},
            {"name": "assessor_style", "location": "query", "type": "string", "required": False, "description": "Optional assessor building_style filter."},
        ],
        "request_example": json.dumps(
            {
                "method": "GET",
                "url": "/api/appeals/P12345/comparables/P54321/improvements/",
                "query": {
                    "roll_year": 2024,
                },
            },
            indent=2,
        ),
        "sample": None,
        "default_path_params": {"parcel_number": "P12345", "comp_parcel": "P54321"},
        "default_querystring": "roll_year=2024",
        "default_body": "",
    },
]


API_PRESETS = [
    {
        "label": "Top 10 Recent Sales",
        "description": "Newest valid sales with parcel context.",
        "endpoint": "sales-list",
        "query": "limit=10&sort=recent",
        "body": "",
    },
    {
        "label": "City District Summary",
        "description": "Average assessed value grouped by district.",
        "endpoint": "parcel-summary",
        "query": "group_by=city_district&metric=avg_assessed_value",
        "body": "",
    },
    {
        "label": "High Value Residential Search",
        "description": "Parcels assessed between $700k and $1.2M mentioning 'St'.",
        "endpoint": "parcel-search",
        "query": "address=St&min_value=700000&max_value=1200000&page_size=25",
        "body": "",
    },
    {
        "label": "Burlington 2km Radius",
        "description": "Nearby parcels within 2km of downtown Burlington.",
        "endpoint": "parcel-nearby",
        "query": "lat=48.4736&lon=-122.3301&radius=2000",
        "body": "",
    },
    {
        "label": "Farmhouse Semantic",
        "description": "Semantic search for modern farmhouse with acreage.",
        "endpoint": "semantic-search",
        "query": "",
        "body": json.dumps({"query": "modern farmhouse with acreage and views"}, indent=2),
    },
]


TOP_SALES_LIMIT = 25
TOP_SALES_BASE_SQL = """
    SELECT
        s.parcel_number,
        s.sale_price,
        s.sale_date,
        s.buyer_name,
        s.seller_name,
        s.sale_type,
        s.recording_number,
        s.deed_type,
        s.excise_number,
        a.address,
        a.assessed_value,
        a.total_market_value,
        a.taxable_value,
        a.acres,
        a.bedrooms,
        a.bathrooms,
        a.living_area,
        a.year_built,
        a.eff_year_built
    FROM sales s
    JOIN assessor a ON a.parcel_number = s.parcel_number
    WHERE LOWER(TRIM(s.sale_type)) = 'valid sale'
      AND s.sale_price IS NOT NULL
      AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
"""


def _clean_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_measure(value: Any, suffix: str, *, decimals: int = 1, include_space: bool = True) -> Optional[str]:
    number = _clean_decimal(value)
    if number is None:
        return None
    num_float = float(number)
    if math.isclose(num_float, round(num_float), rel_tol=0, abs_tol=1e-4):
        display = str(int(round(num_float)))
    else:
        display = f"{num_float:.{decimals}f}".rstrip("0").rstrip(".")
    spacer = " " if include_space else ""
    return f"{display}{spacer}{suffix}"


def _format_living_area(value: Any) -> Optional[str]:
    number = _clean_decimal(value)
    if number is None:
        return None
    return f"{intcomma(int(round(number)))} sq ft"


def _format_sale_date(value: Any) -> str:
    if not value:
        return "Date pending"
    try:
        return f"Closed {date_format(value, 'M j, Y')}"
    except Exception:  # pragma: no cover - defensive
        return "Date pending"


def _format_identifier(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    number = _clean_decimal(value)
    if number is None:
        return str(value)
    if number == number.to_integral():
        return str(int(number))
    return str(number.normalize())


def _delta_metadata(sale_price: Optional[Decimal], assessed_value: Optional[Decimal]) -> Dict[str, Any]:
    if sale_price is None or assessed_value in (None, 0, Decimal("0")):
        return {"display": "—", "class": "text-slate-400", "value": None}
    try:
        diff = (sale_price - assessed_value) / assessed_value * Decimal("100")
    except (InvalidOperation, ZeroDivisionError):
        return {"display": "—", "class": "text-slate-400", "value": None}
    diff_float = float(diff)
    display = f"{diff_float:+.1f}%"
    if diff_float > 0:
        css = "text-emerald-600"
    elif diff_float < 0:
        css = "text-rose-600"
    else:
        css = "text-slate-500"
    return {"display": display, "class": css, "value": diff_float}


def _build_attribute_string(row: Dict[str, Any]) -> str:
    parts = []
    beds = _format_measure(row.get("bedrooms"), "bd", decimals=0)
    if beds:
        parts.append(beds)
    baths = _format_measure(row.get("bathrooms"), "ba", decimals=1)
    if baths:
        parts.append(baths)
    acres = _format_measure(row.get("acres"), "ac", decimals=2)
    if acres:
        parts.append(acres)
    return " • ".join(parts) if parts else "Details unavailable"


def _format_currency(value: Any) -> str:
    number = _clean_decimal(value)
    if number is None:
        return "—"
    return f"${intcomma(int(round(number)))}"


def _clean_address(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Treat common placeholder/import artifacts as missing
    lowered = s.lower()
    if lowered in {"nan", "nan nan, nan", "none", "null", "n/a"}:
        return None
    return s


def _fetch_top_sales(limit: int) -> List[Dict[str, Any]]:
    sql = f"""
        {TOP_SALES_BASE_SQL}
        ORDER BY s.sale_date DESC NULLS LAST
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [limit])
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    results: List[Dict[str, Any]] = []
    for row in rows:
        sale_price_dec = _clean_decimal(row.get("sale_price"))
        sale_price_value = int(sale_price_dec) if sale_price_dec is not None else None
        sale_price_display = _format_currency(row.get("sale_price"))
        assessed_dec = _clean_decimal(row.get("assessed_value"))
        delta = _delta_metadata(sale_price_dec, assessed_dec)
        parcel_number = row.get("parcel_number")
        if not parcel_number:
            continue
        parcel_number = str(parcel_number).strip()
        attributes = _build_attribute_string(row)

        results.append(
            {
                "parcel_number": parcel_number,
                "address": _clean_address(row.get("address")) or "Address unavailable",
                "attributes": attributes,
                "sale_price_display": sale_price_display,
                "sale_price_value": sale_price_value,
                "delta_class": delta["class"],
                "delta_display": delta["display"],
                "sale_date_display": _format_sale_date(row.get("sale_date")),
                "links": {
                    "redfin": f"https://www.redfin.com/parcel/{parcel_number}",
                    "skagit": f"https://www.skagitcounty.net/assessor/?parcel={parcel_number}",
                },
                "modal_url": reverse("parcel-modal-partial", args=[parcel_number]),
            }
        )

    return results


def _fetch_sale_detail(parcel_number: str) -> Optional[Dict[str, Any]]:
    sql = f"""
        {TOP_SALES_BASE_SQL}
          AND s.parcel_number = %s
        ORDER BY s.sale_date DESC NULLS LAST
        LIMIT 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [parcel_number])
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
    if not row:
        return None
    return dict(zip(columns, row))


@require_GET
def top_sales_widget(request):
    """
    HTMX endpoint that renders the Top 25 sales list in a card-based layout.
    """
    results = _fetch_top_sales(TOP_SALES_LIMIT)
    return render(request, "openskagit/partials/top_sales_list.html", {"results": results})


@require_GET
def parcel_modal(request, parcel_number: str):
    """
    Render the parcel detail modal with lazy-loaded sale and valuation data.
    """
    record = _fetch_sale_detail(parcel_number)
    if not record:
        raise Http404("Parcel sale record not found.")

    sale_price_dec = _clean_decimal(record.get("sale_price"))
    assessed_dec = _clean_decimal(record.get("assessed_value"))
    delta = _delta_metadata(sale_price_dec, assessed_dec)

    sale = {
        "sale_price_display": _format_currency(record.get("sale_price")),
        "sale_price_value": int(sale_price_dec) if sale_price_dec is not None else None,
        "sale_date_display": _format_sale_date(record.get("sale_date")),
        "sale_type": (record.get("sale_type") or "").title() or None,
        "buyer_name": record.get("buyer_name"),
        "seller_name": record.get("seller_name"),
        "recording_number": _format_identifier(record.get("recording_number")) or "—",
        "excise_number": _format_identifier(record.get("excise_number")) or "—",
        "deed_type": record.get("deed_type"),
    }

    primary_metrics = [
        {"label": "Bedrooms", "value": _format_measure(record.get("bedrooms"), "bd", decimals=0) or "—"},
        {"label": "Bathrooms", "value": _format_measure(record.get("bathrooms"), "ba", decimals=1) or "—"},
        {"label": "Living Area", "value": _format_living_area(record.get("living_area")) or "—"},
        {"label": "Lot Size", "value": _format_measure(record.get("acres"), "ac", decimals=2) or "—"},
    ]

    valuation_metrics = [
        {"label": "Assessed Value", "value": _format_currency(record.get("assessed_value")), "subtitle": None},
        {"label": "Market Value", "value": _format_currency(record.get("total_market_value")), "subtitle": None},
        {"label": "Taxable Value", "value": _format_currency(record.get("taxable_value")), "subtitle": None},
    ]

    context = {
        "parcel_number": parcel_number,
        "address": _clean_address(record.get("address")) or "Address unavailable",
        "sale": sale,
        "delta": {"display": delta["display"], "class": delta["class"]},
        "primary_metrics": primary_metrics,
        "valuation_metrics": valuation_metrics,
    }
    return render(request, "openskagit/partials/parcel_modal.html", context)


def home(request):
    """
    Render the OpenSkagit portal homepage with chatbot-first interface.
    """
    manager = chat_service.ConversationManager(request)
    requested_id = request.GET.get("cid")
    initial_prompt = (request.GET.get("prompt") or "").strip()
    if initial_prompt:
        initial_prompt = initial_prompt[:1000]
        conversation_id = manager.new()
    else:
        conversation_id = manager.ensure(requested_id)

    context = manager.bootstrap(conversation_id, initial_prompt=initial_prompt or None)
    return render(request, "openskagit/home_portal.html", context)


@require_GET
def chatbot(request):
    """
    Dedicated chat experience with conversation history and streaming responses.
    """

    manager = chat_service.ConversationManager(request)
    requested_id = request.GET.get("cid")
    initial_prompt = (request.GET.get("prompt") or "").strip()
    if initial_prompt:
        initial_prompt = initial_prompt[:1000]
        conversation_id = manager.new()
    else:
        conversation_id = manager.ensure(requested_id)

    context = manager.bootstrap(conversation_id, initial_prompt=initial_prompt)
    return render(request, "openskagit/home.html", context)


@require_GET
def history(request):
    """
    Return the conversation history sidebar HTML.
    """

    manager = chat_service.ConversationManager(request)
    conversations = manager.list_conversations()
    active_id = manager.active_id

    html = render_to_string(
        "partials/history.html",
        {
            "conversations": conversations,
            "active_id": active_id,
        },
        request=request,
    )
    return HttpResponse(html)


@require_POST
def chat(request):
    """
    Stream chat prompts via OpenAI Responses, emitting newline-delimited JSON chunks.
    """

    prompt = (request.POST.get("prompt") or "").strip()
    requested_id = request.POST.get("conversation_id") or None

    if not prompt:
        return HttpResponseBadRequest("Prompt is required.")

    manager = chat_service.ConversationManager(request)
    conversation_id = manager.ensure(requested_id)
    manager.append_user_message(conversation_id, prompt)
    history_messages = manager.model_history(conversation_id)

    def event_stream():
        yield chat_service.render_stream_event({"type": "conversation", "conversation_id": conversation_id})
        try:
            rag_response = llm.generate_rag_response(prompt, history=history_messages)
            final_text = (rag_response.get("answer") or "").strip() or "I wasn't able to craft a response."
            sources = rag_response.get("sources") or []
            model_name = rag_response.get("model") or getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4o-mini")

            manager.append_assistant_message(
                conversation_id,
                final_text,
                sources=sources,
                model=model_name,
            )
            yield chat_service.render_stream_event(
                {
                    "type": "final",
                    "text": final_text,
                    "model": model_name,
                    "sources": sources,
                }
            )
        except (llm.MissingDependency, llm.MissingCredentials) as exc:
            error_text = str(exc)
            manager.append_assistant_message(conversation_id, error_text, sources=[])
            yield chat_service.render_stream_event({"type": "error", "message": error_text})
        except llm.OpenAIError as exc:
            error_text = str(exc) or "The model was unable to finish the response."
            manager.append_assistant_message(conversation_id, error_text, sources=[])
            yield chat_service.render_stream_event({"type": "error", "message": error_text})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Chat request failed: %s", exc)
            error_text = "Something went wrong while contacting the language model. Please try again in a moment."
            manager.append_assistant_message(conversation_id, error_text, sources=[])
            yield chat_service.render_stream_event({"type": "error", "message": error_text})

    response = StreamingHttpResponse(event_stream(), content_type="application/x-ndjson")
    response["Cache-Control"] = "no-cache"
    return response


@require_POST
def chat_new(request):
    """
    Initialize a new empty conversation.
    """

    manager = chat_service.ConversationManager(request)
    conversation_id = manager.new()

    accepts_json = "application/json" in (request.headers.get("Accept") or "")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if accepts_json or is_ajax:
        return JsonResponse({"conversation_id": conversation_id})

    chat_url = f"{reverse('chatbot')}?cid={conversation_id}"
    return redirect(chat_url)


@staff_member_required
@require_POST
def documents_upload(request):
    """
    Accept staff uploads and outline the next ingestion steps.
    """

    files = request.FILES.getlist("documents")
    if not files:
        return HttpResponse(
            "<p class='text-sm text-red-600'>No documents were selected. Choose one or more files to process.</p>",
            status=400,
        )

    filenames = [f.name for f in files]
    guidance = render_to_string(
        "partials/upload_status.html",
        {
            "filenames": filenames,
            "next_command": "python manage.py generate_embeddings",
        },
        request=request,
    )
    # TODO: persist files to storage and enqueue ingestion worker.
    return HttpResponse(guidance)


@staff_member_required
def api_docs(request):
    """
    Render an internal API reference for staff-only access.
    """
    endpoints = []
    for endpoint in API_ENDPOINTS:
        entry = copy.deepcopy(endpoint)
        querystring = entry.get("default_querystring") or ""
        entry["display_path"] = f"{entry['path']}?{querystring}" if querystring else entry["path"]
        if entry.get("request_example"):
            entry["payload_json"] = entry["request_example"]
            entry["payload_label"] = "Sample Request"
        elif entry.get("default_body"):
            entry["payload_json"] = entry["default_body"]
            entry["payload_label"] = "Sample Payload"
        if entry.get("sample"):
            entry["sample_json"] = json.dumps(entry["sample"], indent=2)
        endpoints.append(entry)

    context = {
        "endpoints": endpoints,
        "endpoints_json": json.dumps(endpoints),
        "schema_sql": """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='public';
""".strip(),
        "notes": [
            "All endpoints return JSON responses designed for frontend consumption.",
            "Search endpoints default to page size 25 with optional `page` and `page_size` parameters.",
            "Pass numeric filters as query parameters (e.g. `min_value`, `max_value`, `min_acres`).",
            "Parcel detail responses are organized into sections (valuation, structure, land, sales) to minimize payload size.",
            "Sales leaderboard responses always scope to `sale_type = \"valid sale\"` and include assessor joins for comps.",
            "Sales sorting defaults to descending; set `direction=asc` or `direction=desc` to override.",
            "Semantic search requires embeddings generated in the `assessor.embedding` vector column.",
        ],
    }
    return render(request, "openskagit/api_docs.html", context)


@staff_member_required
def api_dashboard(request):
    """
    Staff-only API playground with request builders and tooling.
    """
    endpoints = copy.deepcopy(API_ENDPOINTS)
    for endpoint in endpoints:
        if endpoint.get("default_body") and isinstance(endpoint["default_body"], str):
            # ensure JSON formatting preserved for UI defaults
            endpoint["default_body"] = endpoint["default_body"]

    context = {
        "endpoints_json": json.dumps(endpoints),
        "presets_json": json.dumps(API_PRESETS),
    }
    return render(request, "openskagit/api_dashboard.html", context)


def _build_cma_context(request, parcel_number: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = params or request.GET
    parcel_state = _get_parcel_state(request, parcel_number)
    filters = cma.parse_filters_from_request(params)
    sort_field, sort_direction = _current_sort(
        request,
        parcel_state,
        params.get("sort_field"),
        params.get("sort_direction"),
    )
    limit = _parse_limit(params.get("limit"))
    raw_view_mode = (params.get("view_mode") or "").strip().lower()
    advanced_mode = raw_view_mode in {"advanced", "adv", "true", "1", "yes", "on"}
    view_mode = "advanced" if advanced_mode else "standard"

    excluded = parcel_state.get("excluded", [])

    rollup_cache: Dict[Tuple[str, Optional[int], Optional[int]], Dict[str, object]] = {}

    try:
        subject = cma.load_subject(parcel_number, rollup_cache=rollup_cache)
    except ValueError as exc:
        return {"error": str(exc)}

    computation = cma.build_comparables(
        subject=subject,
        filters=filters,
        excluded=excluded,
        sort_field=sort_field,
        sort_direction=sort_direction,
        limit=limit,
        load_improvements=advanced_mode,
        rollup_cache=rollup_cache,
    )
    for comparable in computation.comparables:
        setattr(comparable, "adjustment_payload", None)

    advanced_payload: Optional[Dict[str, Any]] = None
    advanced_error: Optional[str] = None
    advanced_summary: Optional[Dict[str, Any]] = None
    if advanced_mode:
        advanced_payload, advanced_error = _compute_adjustment_summary(subject, computation.comparables)
        if advanced_payload:
            comp_map = {item["comp_id"]: item for item in advanced_payload.get("comparables", [])}
            for comparable in computation.comparables:
                comparable.adjustment_payload = comp_map.get(comparable.snapshot.parcel_number)
            advanced_summary = {
                "subject_pred_price": advanced_payload.get("subject_pred_price"),
                "market_group": advanced_payload.get("market_group"),
            }

    return {
        "subject": computation.subject,
        "comparables": computation.comparables,
        "analysis": computation,
        "summary": computation.summary(),
        "filters": filters,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "excluded": excluded,
        "markers": computation.marker_payloads(),
        "limit": limit,
        "view_mode": view_mode,
        "advanced_mode": advanced_mode,
        "advanced_summary": advanced_summary,
        "advanced_error": advanced_error,
        "adjustment_labels": ADJUSTMENT_LABELS,
        "error": None,
    }


@require_GET
def cma_dashboard_view(request, parcel_number: Optional[str] = None):
    context: Dict[str, Any] = {"parcel_number": parcel_number}
    if parcel_number:
        detail_context = _build_cma_context(request, parcel_number)
        context.update(detail_context)
    template_name = "openskagit/cma/dashboard.html"
    if request.headers.get("HX-Request"):
        template_name = "openskagit/cma/partials/dashboard_content.html"
    return render(request, template_name, context)


@require_GET
def cma_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    results = []
    if query:
        start = time.perf_counter()

        results = list(
            Assessor.objects.filter(
                Q(parcel_number__istartswith=query) | Q(address__icontains=query)
            )[:15]
        )

        end = time.perf_counter()
        elapsed = end - start
        logger.info(f"[DEBUG] Parcel search query='{query}' took {elapsed:.3f}s")

    return render(
        request,
        "openskagit/cma/partials/parcel_search_results.html",
        {"query": query, "results": results},
    )



@require_GET
def cma_comparison_grid(request, parcel_number: str):
    context = _build_cma_context(request, parcel_number)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])
    return render(request, "openskagit/cma/partials/comparison_grid.html", context)


@require_GET
def cma_comparable_improvements(request, parcel_number: str, comp_parcel: str):
    def _to_int(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    roll_year = _to_int(request.GET.get("roll_year"))
    roll_id = _to_int(request.GET.get("roll_id"))
    assessor_style = request.GET.get("assessor_style") or None

    improvements = cma.get_improvement_rollup(
        comp_parcel,
        roll_year=roll_year,
        roll_id=roll_id,
        assessor_building_style=assessor_style,
    )

    return render(
        request,
        "openskagit/cma/partials/comparable_improvement_info.html",
        {"improvements": improvements},
    )


@require_POST
def cma_toggle_comparable(request, parcel_number: str, comp_parcel: str):
    _toggle_comparable_inclusion(request, parcel_number, comp_parcel)
    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])
    return render(request, "openskagit/cma/partials/comparison_grid.html", context)


@require_GET
def cma_map_data(request, parcel_number: str):
    params = _merge_request_params(request)
    filters = cma.parse_filters_from_request(params)
    try:
        subject = cma.load_subject(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    comparables = cma.fetch_sales_within_view(subject, filters)
    subject_marker = []
    if subject.geom:
        subject_marker = [
            {
                "parcel_number": subject.parcel_number,
                "lat": subject.geom.y,
                "lon": subject.geom.x,
                "address": subject.address,
                "type": "subject",
            }
        ]
    markers = subject_marker + [dict(marker, **{"type": "comparable"}) for marker in comparables]
    return render(
        request,
        "openskagit/cma/partials/map_payload.html",
        {"markers": markers},
    )


@login_required
@require_POST
def cma_save_analysis(request, parcel_number: str):
    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])

    comparables = context.get("comparables", [])
    if not comparables:
        return HttpResponseBadRequest("At least one comparable is required.")

    analysis_record = CmaAnalysis.objects.create(
        user=request.user,
        subject_parcel=context["subject"].parcel_number,
        subject_snapshot=context["subject"].as_dict(),
        filters=context["filters"].as_dict(),
        manual_adjustments={},
    )

    for comp in comparables:
        CmaComparableSelection.objects.create(
            analysis=analysis_record,
            parcel_number=comp.snapshot.parcel_number,
            included=True,
            rank=comp.inclusion_rank,
            raw_sale_price=comp.sale_price,
            adjusted_sale_price=comp.sale_price,
            gross_percentage_adjustment=Decimal("0"),
            auto_adjustments=[],
            manual_adjustments={},
            metadata=comp.snapshot.as_dict(),
        )

    share_url = request.build_absolute_uri(reverse("cma-share", args=[analysis_record.share_uuid]))
    return render(
        request,
        "openskagit/cma/partials/save_success.html",
        {"share_url": share_url},
    )


@require_GET
def cma_share(request, share_uuid):
    analysis_record = get_object_or_404(CmaAnalysis, share_uuid=share_uuid)
    filters = cma.filters_from_dict(analysis_record.filters)

    try:
        subject = cma.load_subject(analysis_record.subject_parcel)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    computation = cma.build_comparables(
        subject=subject,
        filters=filters,
        excluded=[],
        sort_field="score",
        sort_direction="desc",
        limit=cma.MAX_COMPARABLE_LIMIT,
    )

    saved_rankings = {
        comp.parcel_number: comp.rank for comp in analysis_record.comparables.all().order_by("rank")
    }
    comparables = [
        comp
        for comp in computation.comparables
        if comp.snapshot.parcel_number in saved_rankings
    ]
    for comp in comparables:
        comp.inclusion_rank = saved_rankings.get(comp.snapshot.parcel_number, comp.inclusion_rank)
    comparables.sort(key=lambda item: item.inclusion_rank)

    context = {
        "parcel_number": analysis_record.subject_parcel,
        "subject": computation.subject,
        "comparables": comparables,
        "analysis": computation,
        "summary": computation.summary(),
        "filters": filters,
        "shared_analysis": analysis_record,
        "share_mode": True,
        "markers": computation.marker_payloads(),
    }
    return render(request, "openskagit/cma/dashboard.html", context)


# ------------------------------
# Citizen Appeal Helper (simple)
# ------------------------------

APPEAL_SEARCH_LIMIT = 15
APPEAL_MIN_QUERY_LENGTH = 3


@require_GET
def appeal_home(request):
    """
    Minimal, citizen-friendly entry with a single address/parcel search box.
    """
    manager = chat_service.ConversationManager(request)
    conversation_id = manager.ensure(request.GET.get("cid"))
    chat_bootstrap = manager.bootstrap(conversation_id)
    return render(request, "openskagit/appeal_home_v3.html", {"step": 1, "chat_bootstrap": chat_bootstrap})

APPEAL_SEARCH_LIMIT = 15
APPEAL_MIN_QUERY_LENGTH = 3

@require_GET
def appeal_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    query_too_short = len(query) < APPEAL_MIN_QUERY_LENGTH
    results = []

    if not query_too_short:
        is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
        qs = Parcel.objects.filter(property_type="R")
        # latest_sale = (
        #     Assessor.objects.filter(parcel_number=OuterRef("parcel_number"))
        #     .exclude(sale_price__isnull=True)
        #     .order_by("-roll__year", "-sale_date")
        # )
        # qs = qs.annotate(
        #     sale_price=Subquery(latest_sale.values("sale_price")[:1]),
        #     sale_date=Subquery(latest_sale.values("sale_date")[:1]),
        # )

        if is_parcel_like:
            normalized = query.upper().replace(" ", "")
            digits_only = re.sub(r"\D", "", query)
            filters = []
            if normalized:
                filters.append(Q(parcel_number__startswith=normalized))
            if digits_only:
                filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
            if filters:
                qs = qs.filter(functools.reduce(operator.or_, filters))
        else:
            starts_with_number = bool(re.match(r"^\s*\d+", query))
            if starts_with_number:
                qs = qs.filter(address__istartswith=query)
            else:
                qs = qs.filter(address__icontains=query)

        # Safety + result cap
        results = (
            qs.exclude(address__isnull=True)
              .exclude(address__exact="")
              .exclude(address__icontains="nan")
              .order_by("parcel_number")[:APPEAL_SEARCH_LIMIT]
        )

    manager = chat_service.ConversationManager(request)
    conversation_id = manager.ensure(request.GET.get("cid"))
    chat_bootstrap = manager.bootstrap(conversation_id)

    return render(
        request,
        "openskagit/appeal_parcel_search_results_v3.html",
        {
            "query": query,
            "results": results,
            "query_too_short": query_too_short,
            "min_search_length": APPEAL_MIN_QUERY_LENGTH,
            "chat_bootstrap": chat_bootstrap,
        },
    )


@require_GET
def appeal_result(request, parcel_number: str):
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    neighborhood = appeals.get_subject_neighborhood_snapshot(subject)
    subject_year_built = subject.year_built or subject.effective_year_built

    neighborhood_geom_geojson = None
    if neighborhood and neighborhood.get("code"):
        try:
            geom = NeighborhoodGeom.objects.get(code=neighborhood["code"])
            neighborhood_geom_geojson = json.loads(geom.geom_4326.geojson)
        except NeighborhoodGeom.DoesNotExist:
            neighborhood_geom_geojson = None

    comparables_url = request.path + "comparables/"
    manager = chat_service.ConversationManager(request)
    conversation_id = manager.ensure(request.GET.get("cid"))
    chat_bootstrap = manager.bootstrap(conversation_id)

    parcel_history_points = _parcel_value_history(parcel_number)

    return render(
        request,
        "openskagit/appeal_results_v3.html",
        {
            "subject": subject,
            "parcel_number": parcel_number,
            "neighborhood": neighborhood,
            "neighborhood_geom_geojson": neighborhood_geom_geojson,
            "subject_year_built": subject_year_built,
            "comparables_url": comparables_url,
            "parcel_history_points": parcel_history_points,
            "step": 2,
            "chat_bootstrap": chat_bootstrap,
        },
    )


@require_GET
def appeal_result_comparables(request, parcel_number: str):
    request_start = time.perf_counter()
    subject_start = time.perf_counter()
    raw_view_mode = (request.GET.get("view_mode") or "").strip().lower()
    advanced_mode = raw_view_mode in {"advanced", "adv", "true", "1", "yes", "on"}
    view_mode = "advanced" if advanced_mode else "standard"
    try:
        subject, _ = appeals.load_subject_with_roll_context(parcel_number)
    except ValueError as exc:
        subject_elapsed = time.perf_counter() - subject_start
        _log_comparables_step(
            parcel_number,
            "load_subject",
            subject_elapsed,
            error=str(exc),
        )
        return HttpResponseBadRequest(str(exc))
    subject_elapsed = time.perf_counter() - subject_start
    _log_comparables_step(parcel_number, "load_subject", subject_elapsed)

    requested_count = int(request.GET.get("count", appeals.INITIAL_COMPARABLE_LIMIT))
    display_limit = (
        appeals.EXTENDED_COMPARABLE_LIMIT
        if requested_count >= appeals.EXTENDED_COMPARABLE_LIMIT
        else appeals.INITIAL_COMPARABLE_LIMIT
    )
    comps_start = time.perf_counter()
    comps, radius_used = appeals._comparable_candidates(subject, display_limit)
    comps_elapsed = time.perf_counter() - comps_start
    _log_comparables_step(
        parcel_number,
        "fetch_candidates",
        comps_elapsed,
        comp_count=len(comps),
        radius=radius_used,
        requested=requested_count,
        limit=display_limit,
    )

    summary_start = time.perf_counter()
    summary = appeals.citizen_assessment_summary(
        subject,
        comparables=comps,
        radius_meters=radius_used,
        limit=display_limit,
    )
    summary_elapsed = time.perf_counter() - summary_start
    summary_comps = summary.get("comparables") or []
    _log_comparables_step(
        parcel_number,
        "summarize",
        summary_elapsed,
        summary_count=len(summary_comps),
        score=summary.get("score"),
        radius=radius_used,
        limit=display_limit,
    )

    over_pct = summary.get("over_assessment_pct")
    comp_count = summary.get("comp_count") or 0
    neigh = summary.get("neighborhood") or {}
    neigh_diff = summary.get("neigh_diff_pct")
    avg_change_pct = neigh.get("avg_increase_pct")
    your_change_pct = appeals.extract_assessment_change_pct(subject.metadata)
    if your_change_pct is None and avg_change_pct is not None and neigh_diff is not None:
        your_change_pct = avg_change_pct + neigh_diff
    if neigh_diff is None and avg_change_pct is not None and your_change_pct is not None:
        neigh_diff = your_change_pct - avg_change_pct

    score = summary.get("score") or 0
    subject_meta = getattr(subject, "metadata", {}) or {}
    subject_area = _safe_float_value(getattr(subject, "living_area", None))
    subject_lot = _safe_float_value(
        getattr(subject, "acres", None)
        or getattr(subject, "lot_acres", None)
        or subject_meta.get("lot_acres")
    )
    subject_quality = subject_meta.get("quality_score")
    subject_condition = subject_meta.get("condition_score")

    soft_stop = False
    soft_reasons: List[str] = []
    if over_pct is not None and over_pct < 7:
        soft_stop = True
        soft_reasons.append("Assessed value is less than ~7% above market comps.")
    if comp_count < 3:
        soft_stop = True
        soft_reasons.append("Fewer than 3 strong comparable sales are available.")
    if (neigh_diff is not None) and neigh_diff <= 0:
        soft_stop = True
        soft_reasons.append("Your assessment did not rise more than your neighborhood average.")
    if score < 45:
        soft_stop = True
        soft_reasons.append("Overall appeal likelihood is below ~45%.")

    has_more = len(comps) == display_limit and display_limit < appeals.EXTENDED_COMPARABLE_LIMIT
    load_more_url = f"{request.path}?count={appeals.EXTENDED_COMPARABLE_LIMIT}"

    total_elapsed = time.perf_counter() - request_start
    _log_comparables_step(
        parcel_number,
        "request",
        total_elapsed,
        comp_count=len(summary_comps),
        score=score,
        limit=display_limit,
    )

    # Flatten comparable results for v3 templates (which expect simple dicts)
    view_comps = []
    adjustment_map: Dict[str, Dict[str, Any]] = {}
    advanced_payload: Optional[Dict[str, Any]] = None
    advanced_error: Optional[str] = None
    advanced_summary: Optional[Dict[str, Any]] = None
    if advanced_mode:
        advanced_payload, advanced_error = _compute_adjustment_summary(subject, comps)
        if advanced_payload:
            adjustment_map = {
                str(item.get("comp_id")): item for item in advanced_payload.get("comparables", [])
            }
            advanced_summary = {
                "subject_pred_price": advanced_payload.get("subject_pred_price"),
                "market_group": advanced_payload.get("market_group"),
            }

    for c in comps:
        snapshot = getattr(c, "snapshot", None)
        address = getattr(snapshot, "address", None) if snapshot else None
        bedrooms = getattr(snapshot, "bedrooms", None) if snapshot else None
        bathrooms = getattr(snapshot, "bathrooms", None) if snapshot else None
        living_area = getattr(snapshot, "living_area", None) if snapshot else None
        year_built = getattr(snapshot, "year_built", None) if snapshot else None
        geom = getattr(snapshot, "geom", None) if snapshot else None
        lat, lon = _centroid_lat_lon(geom)
        try:
            sqft = float(living_area) if living_area not in (None, 0) else None
        except Exception:
            sqft = None
        try:
            price = float(c.sale_price) if c.sale_price is not None else None
        except Exception:
            price = None
        price_per_sqft = None
        if price is not None and sqft not in (None, 0):
            try:
                price_per_sqft = price / sqft
            except Exception:
                price_per_sqft = None
        comp_id = getattr(snapshot, "parcel_number", None) if snapshot else None
        adjustments = adjustment_map.get(str(comp_id)) if comp_id else None
        comp_meta = getattr(snapshot, "metadata", {}) or {}
        comp_living_area = _safe_float_value(living_area)
        comp_lot_value = _safe_float_value(
            getattr(snapshot, "acres", None)
            or getattr(snapshot, "lot_acres", None)
            or comp_meta.get("lot_acres")
        )
        comp_score_obj = getattr(c, "score", None)
        proximity_score = (
            _safe_float_value(getattr(comp_score_obj, "location_score", None))
            if comp_score_obj
            else None
        )
        time_score = (
            _safe_float_value(getattr(comp_score_obj, "time_score", None))
            if comp_score_obj
            else None
        )
        size_ratio = _ratio_similarity(subject_area, comp_living_area)
        land_ratio = _ratio_similarity(subject_lot, comp_lot_value)
        quality_match = _match_text_score(subject_quality, comp_meta.get("quality_score"))
        condition_match = _match_text_score(subject_condition, comp_meta.get("condition_score"))
        quality_condition_ratio = _average_score([quality_match, condition_match])
        available_ratios = [
            value
            for value in (
                proximity_score,
                time_score,
                size_ratio,
                quality_condition_ratio,
                land_ratio,
            )
            if value is not None
        ]
        overall_ratio = _average_score(available_ratios)
        if overall_ratio is None:
            fallback_total = (
                _safe_float_value(getattr(comp_score_obj, "total_score", None))
                if comp_score_obj
                else None
            )
            overall_ratio = fallback_total
        if overall_ratio is None:
            overall_ratio = 0.0
        else:
            overall_ratio = max(0.0, min(1.0, overall_ratio))
        similarity = {
            "overall": _percentage_score(overall_ratio),
            "time": _percentage_score(time_score),
            "proximity": _percentage_score(proximity_score),
            "size": _percentage_score(size_ratio),
            "quality_condition": _percentage_score(quality_condition_ratio),
            "land": _percentage_score(land_ratio),
        }
        view_comps.append(
            {
                "parcel_number": getattr(snapshot, "parcel_number", None) if snapshot else None,
                "address": address,
                "sale_price": c.sale_price,
                "sale_date": c.sale_date,
                "distance_miles": c.distance_miles,
                "assessed_value": c.assessed_value,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "living_area": living_area,
                "year_built": year_built,
                "price_per_sqft": price_per_sqft,
                "latitude": lat,
                "longitude": lon,
                "adjusted_value": adjustments.get("adjusted_value") if adjustments else None,
                "total_adjustment": adjustments.get("total_adjustment") if adjustments else None,
                "adjustments": adjustments.get("adjustment_list") if adjustments else [],
                "similarity": similarity,
            }
        )

    # Expose subject coordinates for map rendering if available
    try:
        geom = getattr(subject, "geom", None)
        lat, lon = _centroid_lat_lon(geom)
        existing_lat = getattr(subject, "latitude", None)
        existing_lon = getattr(subject, "longitude", None)
        if lat is not None and lon is not None and (
            existing_lat is None or existing_lon is None
        ):
            setattr(subject, "latitude", lat)
            setattr(subject, "longitude", lon)
    except Exception:
        pass

    manager = chat_service.ConversationManager(request)
    conversation_id = manager.ensure(request.GET.get("cid"))
    chat_bootstrap = manager.bootstrap(conversation_id)

    return render(
        request,
        "openskagit/appeal_results_comparables_v3.html",
        {
            "subject": subject,
            "comparables": view_comps,
            "soft_stop": soft_stop,
            "soft_reasons": soft_reasons,
            "score": score,
            "rating": summary.get("rating"),
            "reasons": summary.get("reasons", []),
            "has_more": has_more,
            "load_more_url": load_more_url,
            "parcel_number": parcel_number,
            "view_mode": view_mode,
            "advanced_mode": advanced_mode,
            "advanced_summary": advanced_summary,
            "advanced_error": advanced_error,
            "adjustment_labels": ADJUSTMENT_LABELS,
            "radius_meters_used": radius_used,
            "fetch_url": request.path,
            "chat_bootstrap": chat_bootstrap,
        },
    )


@require_GET
def appeal_fairness_analysis(request, parcel_number: str):
    """
    Run an on-demand fairness analysis that blends subject, neighborhood,
    and comparable sales metrics using IAAO-style concepts.
    """
    pn = (parcel_number or "").strip()
    if not pn:
        return HttpResponseBadRequest("Parcel number is required.")

    try:
        subject, _ = appeals.load_subject_with_roll_context(pn)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    summary = appeals.citizen_assessment_summary(subject)
    comparables = summary.get("comparables") or []
    neighborhood = summary.get("neighborhood") or {}

    def _to_float(value: Any) -> Optional[float]:
        if value in (None, "", "null"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError, InvalidOperation):
            return None

    def _serialize_subject(snapshot: cma.PropertySnapshot) -> Dict[str, Any]:
        metadata = snapshot.metadata if isinstance(snapshot.metadata, dict) else {}
        return {
            "parcel_number": snapshot.parcel_number,
            "address": snapshot.address,
            "assessed_value": _to_float(snapshot.assessed_value or metadata.get("assessed_value")),
            "sale_price": _to_float(snapshot.sale_price),
            "sale_date": snapshot.sale_date.isoformat() if snapshot.sale_date else None,
            "bedrooms": _to_float(snapshot.bedrooms),
            "bathrooms": _to_float(snapshot.bathrooms),
            "living_area_sqft": _to_float(snapshot.living_area),
            "year_built": snapshot.year_built or snapshot.effective_year_built,
            "neighborhood_code": metadata.get("neighborhood_code"),
            "valuation_area": metadata.get("valuation_area"),
            "assessment_roll_year": metadata.get("assessment_roll_year"),
        }

    def _serialize_comparable(comp: cma.ComparableResult) -> Dict[str, Any]:
        snapshot = getattr(comp, "snapshot", None)
        address = getattr(snapshot, "address", None) if snapshot else None
        bedrooms = getattr(snapshot, "bedrooms", None) if snapshot else None
        bathrooms = getattr(snapshot, "bathrooms", None) if snapshot else None
        living_area = getattr(snapshot, "living_area", None) if snapshot else None
        year_built = getattr(snapshot, "year_built", None) if snapshot else None
        return {
            "parcel_number": getattr(snapshot, "parcel_number", None) if snapshot else None,
            "address": address,
            "sale_price": _to_float(comp.sale_price),
            "sale_date": comp.sale_date.isoformat() if comp.sale_date else None,
            "assessed_value": _to_float(comp.assessed_value),
            "distance_miles": _to_float(comp.distance_miles),
            "bedrooms": _to_float(bedrooms),
            "bathrooms": _to_float(bathrooms),
            "living_area_sqft": _to_float(living_area),
            "year_built": year_built,
        }

    serialized_comps = [_serialize_comparable(c) for c in comparables]

    # Basic fairness metrics grounded in IAAO concepts:
    #   - level (sales ratio / median ratio)
    #   - uniformity (COD)
    #   - vertical equity (PRD)
    neighborhood_cod = _to_float(neighborhood.get("cod"))
    neighborhood_prd = _to_float(neighborhood.get("prd"))
    neighborhood_sales_ratio = _to_float(neighborhood.get("sales_ratio"))
    over_assessment_pct = summary.get("over_assessment_pct")
    comp_count = summary.get("comp_count") or 0
    score = summary.get("score")
    rating = summary.get("rating")

    metrics: Dict[str, Any] = {
        "over_assessment_pct": _to_float(over_assessment_pct),
        "comp_count": comp_count,
        "appeal_score": _to_float(score),
        "appeal_rating": rating,
        "cod": neighborhood_cod,
        "prd": neighborhood_prd,
        "sales_ratio": neighborhood_sales_ratio,
    }

    # Status buckets for quick visual flags
    def _level_status(ratio: Optional[float]) -> Dict[str, Any]:
        if ratio is None:
            return {
                "label": "Level unknown",
                "severity": "unknown",
                "description": "We could not calculate a neighborhood sales ratio.",
            }
        if 90 <= ratio <= 110:
            return {
                "label": "Within IAAO range",
                "severity": "ok",
                "description": "Neighborhood level is broadly aligned with the IAAO 90–110% target range.",
            }
        return {
            "label": "Outside IAAO range",
            "severity": "watch",
            "description": "Neighborhood level appears outside the typical 90–110% IAAO range.",
        }

    def _cod_status(cod_value: Optional[float]) -> Dict[str, Any]:
        if cod_value is None:
            return {
                "label": "Uniformity unknown",
                "severity": "unknown",
                "description": "We do not have a COD metric for this neighborhood.",
            }
        if cod_value < 10:
            return {
                "label": "Excellent uniformity",
                "severity": "ok",
                "description": "COD below ~10 suggests very consistent assessments among similar properties.",
            }
        if cod_value < 15:
            return {
                "label": "Acceptable uniformity",
                "severity": "ok",
                "description": "COD between ~10–15 is generally viewed as acceptable for residential property.",
            }
        return {
            "label": "Patchy uniformity",
            "severity": "watch",
            "description": "COD above ~15 suggests assessments vary more than IAAO guidelines recommend.",
        }

    def _prd_status(prd_value: Optional[float]) -> Dict[str, Any]:
        if prd_value is None:
            return {
                "label": "Vertical equity unknown",
                "severity": "unknown",
                "description": "We do not have a PRD metric for this neighborhood.",
            }
        if 0.98 <= prd_value <= 1.03:
            return {
                "label": "Balanced by value",
                "severity": "ok",
                "description": "High- and low-value properties appear to be assessed at similar ratios.",
            }
        if prd_value > 1.03:
            return {
                "label": "Regressive pattern",
                "severity": "concern",
                "description": "Higher-value properties tend to be under-assessed relative to lower-value homes.",
            }
        return {
            "label": "Progressive pattern",
            "severity": "watch",
            "description": "Higher-value properties tend to be over-assessed relative to lower-value homes.",
        }

    level_status = _level_status(neighborhood_sales_ratio)
    cod_status = _cod_status(neighborhood_cod)
    prd_status = _prd_status(neighborhood_prd)

    context_payload = {
        "subject": _serialize_subject(subject),
        "neighborhood": {
            "code": neighborhood.get("code"),
            "name": neighborhood.get("name"),
            "year": neighborhood.get("year"),
            "cod": neighborhood_cod,
            "prd": neighborhood_prd,
            "sales_ratio": neighborhood_sales_ratio,
            "reliability": neighborhood.get("reliability"),
            "reliability_display": neighborhood.get("reliability_display"),
            "valid_sales": neighborhood.get("valid_sales"),
            "parcels": neighborhood.get("parcels"),
        },
        "comparables": serialized_comps,
        "metrics": metrics,
    }

    system_prompt = (
        "You are a property tax fairness reviewer for a county assessor's office. "
        "Use IAAO mass appraisal standards around level, uniformity (COD), and price-related bias (PRD). "
        "Explain findings for residents in plain language, without legal advice."
        "talk to a citizen that doesn't have a lot of knowledge about all this.  instead of the subject, say, your house."
        "talk directly to home owner"
    )

    context_json = json.dumps(context_payload, ensure_ascii=False)

    user_prompt = (
        "Review this property-tax context and provide a fairness analysis.\n\n"
        "Context JSON (read-only):\n"
        f"{context_json}\n\n"
        "Using IAAO concepts:\n"
        "  - Level: Are assessments near 100% of market value (90–110% band)?\n"
        "  - Uniformity: Is COD in an acceptable range for residential property?\n"
        "  - Vertical equity: Does PRD suggest regressivity or progressivity?\n\n"
        "Return STRICT JSON with this exact shape and no extra commentary:\n"
        "{\n"
        '  "summary": "2–3 sentence plain-language overview.",\n'
        '  "subject_vs_neighborhood": ["bullet-style insight", "..."],\n'
        '  "subject_vs_comparables": ["bullet-style insight", "..."],\n'
        '  "fairness_flags": [\n'
        '    {"label": "Horizontal equity", "severity": "info|watch|concern", "detail": "..."}\n'
        "  ],\n"
        '  "iaao_signals": "Short explanation of what COD, PRD, and sales ratios suggest.",\n'
        '  "next_steps": ["Concrete, non-legal suggestions for the homeowner"],\n'
        '  "disclaimer": "Short reminder that this is not legal advice."\n'
        "}\n"
    )

    analysis: Dict[str, Any] = {
        "summary": "",
        "subject_vs_neighborhood": [],
        "subject_vs_comparables": [],
        "fairness_flags": [],
        "iaao_signals": "",
        "next_steps": [],
        "disclaimer": "",
    }
    analysis_error: Optional[str] = None
    raw_text: str = ""

    try:
        client = llm.get_openai_client()
        model_name = getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4o-mini")
        response = client.responses.create(
            model=model_name,
            input=str(f"System Prompt {system_prompt}, User Prompt: {user_prompt}"),
            temperature=0.2,
        )
        raw_text = getattr(response, "output_text", "") or ""
        text = raw_text.strip()
        try:
            if text:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    analysis.update(parsed)
                else:
                    analysis["summary"] = text
        except json.JSONDecodeError:
            # Fall back to wrapping the model text as a simple summary.
            analysis["summary"] = text
    except llm.MissingCredentials as exc:
        analysis_error = str(exc)
    except llm.MissingDependency as exc:
        analysis_error = str(exc)
    except llm.OpenAIError as exc:
        analysis_error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error during fairness analysis for parcel %s", pn)
        analysis_error = str(exc)

    history_points = _load_neighborhood_sales_ratio_history(neighborhood.get("code"))

    subject_over_pct = metrics.get("over_assessment_pct")
    subject_ratio_pct = None if subject_over_pct is None else 100 + subject_over_pct
    distribution_context = {
        "subject_ratio": subject_ratio_pct,
        "neighborhood_median_ratio": neighborhood.get("median_ratio_pct"),
        "iaao_range": {"low": 90, "high": 110},
    }

    adjustment_payload, adjustment_error = _compute_adjustment_summary(subject, comparables)
    adjustment_storyboard = []
    if adjustment_payload:
        adjustment_storyboard = _prepare_adjustment_storyboard(adjustment_payload, subject, comparables)

    horizontal_diff = None
    if subject_ratio_pct is not None and neighborhood_sales_ratio is not None:
        horizontal_diff = subject_ratio_pct - neighborhood_sales_ratio

    radar_data = {
        "level_ratio": neighborhood_sales_ratio,
        "uniformity": neighborhood_cod,
        "horizontal_diff": horizontal_diff,
        "vertical_prd": neighborhood_prd,
        "over_under_pct": metrics.get("over_assessment_pct"),
    }

    appeal_gauge = {
        "score": metrics.get("appeal_score"),
        "rating": metrics.get("appeal_rating") or rating,
    }

    context = {
        "subject": subject,
        "parcel_number": pn,
        "neighborhood": neighborhood,
        "metrics": metrics,
        "level_status": level_status,
        "cod_status": cod_status,
        "prd_status": prd_status,
        "history_points": history_points,
        "distribution_context": distribution_context,
        "adjustment_storyboard": adjustment_storyboard,
        "adjustment_error": adjustment_error,
        "radar_data": radar_data,
        "appeal_gauge": appeal_gauge,
        "analysis": analysis,
        "analysis_error": analysis_error,
        "analysis_raw_text": raw_text,
    }

    return render(request, "openskagit/appeal_fairness_analysis_v3.html", context)


@require_GET
def methodology_view(request):
    """
    Public-facing page explaining the regression methodology used for property valuations.
    Shows real coefficients and model performance metrics for transparency.
    """
    from .models import AdjustmentCoefficient
    from django.db.models import Max

    latest_run = AdjustmentCoefficient.objects.aggregate(Max('created_at'))['created_at__max']

    market_groups = AdjustmentCoefficient.objects.values('market_group').distinct().order_by('market_group')

    coefficients_by_group = {}
    for mg in market_groups:
        group_name = mg['market_group']
        coeffs = AdjustmentCoefficient.objects.filter(
            market_group=group_name,
            created_at=latest_run
        ).order_by('term')

        coefficients_by_group[group_name] = {
            'coefficients': list(coeffs),
            'display_name': group_name.replace('_', ' ').title()
        }

    model_stats = {
        'ANACORTES': {'n': 4798, 'r2': 0.928, 'adj_r2': 0.928, 'COD': 6.92, 'PRD': 1.181, 'median_ratio': 0.995},
        'BURLINGTON': {'n': 2852, 'r2': 0.931, 'adj_r2': 0.930, 'COD': 5.65, 'PRD': 1.151, 'median_ratio': 0.998},
        'CONCRETE': {'n': 833, 'r2': 0.923, 'adj_r2': 0.921, 'COD': 7.40, 'PRD': 1.216, 'median_ratio': 0.992},
        'LACONNER_CONWAY': {'n': 698, 'r2': 0.937, 'adj_r2': 0.936, 'COD': 6.78, 'PRD': 1.179, 'median_ratio': 1.000},
        'MOUNT_VERNON': {'n': 9012, 'r2': 0.935, 'adj_r2': 0.935, 'COD': 4.92, 'PRD': 1.130, 'median_ratio': 1.000},
        'SEDRO_WOOLLEY': {'n': 5215, 'r2': 0.929, 'adj_r2': 0.928, 'COD': 7.12, 'PRD': 1.178, 'median_ratio': 0.995},
    }

    feature_explanations = [
        {
            'term': 'log_area',
            'simple': 'Living Area (Square Feet)',
            'explanation': 'Larger homes typically sell for more. We use a logarithmic transformation because each additional square foot has diminishing returns.',
            'example': 'A 2,000 sq ft home vs 1,500 sq ft might be worth $50,000 more, but going from 3,000 to 3,500 sq ft adds less.'
        },
        {
            'term': 'log_lot',
            'simple': 'Lot Size (Acres)',
            'explanation': 'Larger lots generally increase property value, especially in rural areas.',
            'example': 'A half-acre lot is worth more than a quarter-acre, but the premium decreases as lots get very large.'
        },
        {
            'term': 'log_age',
            'simple': 'Property Age (Years)',
            'explanation': 'Newer homes typically command higher prices, though well-maintained older homes can hold value.',
            'example': 'A 5-year-old home might sell for more than a 25-year-old home of similar size.'
        },
        {
            'term': 't',
            'simple': 'Time Trend',
            'explanation': 'Market conditions change over time. This captures whether prices are rising or falling.',
            'example': 'Properties sold in 2023 might have different values than identical properties sold in 2021.'
        },
        {
            'term': 'quality_score',
            'simple': 'Construction Quality',
            'explanation': 'Higher quality materials and finishes increase home value.',
            'example': 'Granite counters and hardwood floors vs laminate counters and vinyl flooring.'
        },
        {
            'term': 'condition_score',
            'simple': 'Property Condition',
            'explanation': 'Well-maintained properties are worth more than those needing repairs.',
            'example': 'A home with a new roof and fresh paint vs one needing significant updates.'
        },
        {
            'term': 'has_garage',
            'simple': 'Garage Present',
            'explanation': 'Properties with garages typically sell for more than those without.',
            'example': 'An attached 2-car garage adds value for storage and convenience.'
        },
        {
            'term': 'has_basement',
            'simple': 'Basement Present',
            'explanation': 'Finished or unfinished basements add usable space and value.',
            'example': 'Additional storage, living space, or potential for future expansion.'
        },
        {
            'term': 'is_view',
            'simple': 'View Premium',
            'explanation': 'Properties with water, mountain, or other desirable views command premium prices.',
            'example': 'Homes with Puget Sound views or mountain vistas in specific neighborhoods.'
        },
        {
            'term': 'area_time',
            'simple': 'Size × Time Interaction',
            'explanation': 'How the market values home size can change over time. Larger homes may appreciate differently than smaller ones.',
            'example': 'During certain market periods, larger homes may see stronger price growth.'
        },
    ]

    context = {
        'coefficients_by_group': coefficients_by_group,
        'model_stats': model_stats,
        'feature_explanations': feature_explanations,
        'last_updated': latest_run,
        'total_observations': sum(stats['n'] for stats in model_stats.values()),
    }

    return render(request, 'openskagit/methodology.html', context)


@require_GET
def faq_view(request):
    """
    Frequently Asked Questions page with searchable, categorized content.
    """
    return render(request, 'openskagit/faq.html')


def hood_trend_list(request):
    """
    Left-hand panel: list of hoods that have trends.
    HTMX will pull the detail view on click.
    """
    hoods = (
        NeighborhoodTrend.objects.values("hood_id")
        .annotate(
            first_year=Min("value_year"),
            last_year=Max("value_year"),
            n_years=Count("id"),
            avg_stability=Avg("stability_score"),
        )
        .order_by("hood_id")
    )

    return render(request, "trends/hood_trend_list.html", {"hoods": hoods})


def hood_trend_detail(request, hood_id):
    """
    Right-hand panel: full time series for one hood.
    """
    qs = NeighborhoodTrend.objects.filter(hood_id=hood_id).order_by("value_year")
    if not qs.exists():
        return render(
            request, "trends/hood_trend_detail.html", {"hood": hood_id, "rows": []}
        )

    rows = list(qs)

    first_year = rows[0].value_year
    last_year = rows[-1].value_year
    avg_stability = sum(r.stability_score or 0 for r in rows) / max(
        len([r for r in rows if r.stability_score is not None]), 1
    )

    context = {
        "hood": hood_id,
        "rows": rows,
        "first_year": first_year,
        "last_year": last_year,
        "avg_stability": round(avg_stability, 1),
    }

    return render(request, "trends/hood_trend_detail.html", context)


NEIGHBORHOOD_TRENDS_SEARCH_LIMIT = 15
NEIGHBORHOOD_TRENDS_MIN_QUERY_LENGTH = 3


@require_GET
def neighborhood_trends_page(request):
    """
    Entry point for the Neighborhood Trends tool.
    """
    hoods = (
        NeighborhoodTrend.objects.values("hood_id")
        .annotate(
            first_year=Min("value_year"),
            last_year=Max("value_year"),
            avg_stability=Avg("stability_score"),
        )
        .order_by("hood_id")
    )

    return render(
        request,
        "openskagit/neighborhood_trends_page.html",
        {
            "hoods": hoods,
            "cesium_token": getattr(settings, "CESIUM_ION_TOKEN", None),
        },
    )


@require_GET
def neighborhood_trend_data(request, hood_id):
    """
    Chart-specific JSON payload with yearly trend arrays.
    """
    rows = list(
        NeighborhoodTrend.objects.filter(hood_id=hood_id).order_by("value_year")
    )
    if not rows:
        empty_series = {
            "years": [],
            "median_market_total": [],
            "median_land_market": [],
            "median_building": [],
            "median_tax_amount": [],
            "yoy_change_total": [],
            "tax_percent_of_value": [],
        }
        return JsonResponse(
            {
                "hood_id": hood_id,
                "years": [],
                "series": empty_series,
                "summary": {"first_year": None, "last_year": None, "avg_stability": None},
            }
        )

    series = {
        "median_market_total": [],
        "median_land_market": [],
        "median_building": [],
        "median_tax_amount": [],
        "yoy_change_total": [],
        "tax_percent_of_value": [],
    }
    stability_values = []

    for row in rows:
        series["median_market_total"].append(row.median_market_total)
        series["median_land_market"].append(row.median_land_market)
        series["median_building"].append(row.median_building)
        series["median_tax_amount"].append(row.median_tax_amount)
        series["yoy_change_total"].append(row.yoy_change_total)

        if row.median_market_total and row.median_tax_amount:
            series["tax_percent_of_value"].append(
                round(row.median_tax_amount / row.median_market_total * 100, 2)
            )
        else:
            series["tax_percent_of_value"].append(None)

        if row.stability_score is not None:
            stability_values.append(row.stability_score)

    avg_stability = (
        round(sum(stability_values) / len(stability_values), 1)
        if stability_values
        else None
    )

    summary = {
        "first_year": rows[0].value_year,
        "last_year": rows[-1].value_year,
        "avg_stability": avg_stability,
    }

    return JsonResponse(
        {
            "hood_id": hood_id,
            "years": [row.value_year for row in rows],
            "series": series,
            "summary": summary,
        }
    )


@require_GET
def neighborhood_trend_geom(request, hood_id):
    """
    GeoJSON payload for the selected neighborhood polygon.
    """
    try:
        geom_record = NeighborhoodGeom.objects.get(code=hood_id)
    except NeighborhoodGeom.DoesNotExist:
        return JsonResponse(
            {"hood_id": hood_id, "name": None, "geom": None, "centroid": None}
        )

    geom_obj = getattr(geom_record, "geom_4326", None)
    centroid_lat, centroid_lon = _centroid_lat_lon(geom_obj)

    return JsonResponse(
        {
            "hood_id": hood_id,
            "name": geom_record.name or geom_record.code,
            "geom": json.loads(geom_obj.geojson) if geom_obj else None,
            "centroid": {"lat": centroid_lat, "lng": centroid_lon},
        }
    )


@require_GET
def neighborhood_trend_address_search(request):
    """
    Address autocomplete for selecting a neighborhood via parcel search.
    """
    query = (request.GET.get("q") or "").strip()
    query_too_short = len(query) < NEIGHBORHOOD_TRENDS_MIN_QUERY_LENGTH
    results = []

    if not query_too_short:
        qs = (
            Parcel.objects.filter(
                neighborhood_code__isnull=False
            )
            .exclude(neighborhood_code__exact="")
            .exclude(address__isnull=True)
            .exclude(address__exact="")
        )

        is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
        if is_parcel_like:
            normalized = query.upper().replace(" ", "")
            digits_only = re.sub(r"\D", "", query)
            filters = []
            if normalized:
                filters.append(Q(parcel_number__startswith=normalized))
            if digits_only:
                filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
            if filters:
                qs = qs.filter(functools.reduce(operator.or_, filters))
        else:
            starts_with_number = bool(re.match(r"^\s*\d+", query))
            if starts_with_number:
                qs = qs.filter(address__istartswith=query)
            else:
                qs = qs.filter(address__icontains=query)

        results = (
            qs.order_by("address")
            [:NEIGHBORHOOD_TRENDS_SEARCH_LIMIT]
        )

    return render(
        request,
        "openskagit/neighborhood_trends_search_results.html",
        {
            "query": query,
            "query_too_short": query_too_short,
            "results": results,
            "min_search_length": NEIGHBORHOOD_TRENDS_MIN_QUERY_LENGTH,
        },
    )
