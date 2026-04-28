from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.contrib.gis.geos import Point
from django.utils import timezone

from . import cma
from .neighborhood import get_neighborhood_snapshot
from .services.sales_comps import DEFAULT_LOOKBACK_MONTHS, build_sales_comps_v2


logger = logging.getLogger(__name__)


def _empty_neighborhood_snapshot(raw_code: Optional[str]) -> Dict[str, Any]:
    """
    Provide a consistent schema when we cannot resolve official neighborhood metrics.
    """
    normalized = (raw_code or "").strip()
    normalized_upper = normalized.upper() if normalized else None
    return {
        "code": normalized_upper or raw_code,
        "name": None,
        "year": None,
        "avg_increase_pct": None,
        "cod": None,
        "valid_sales": None,
        "parcels": None,
        "reliability": None,
        "reliability_display": "Unknown",
        "sales_ratio": None,
        "median_ratio": None,
        "median_ratio_pct": None,
        "prior_sales_ratio": None,
        "sales_ratio_delta": None,
        "prior_cod": None,
        "prd": None,
        "prior_prd": None,
        "sample_size_pct": None,
        "sales_ratio_pos": None,
        "prd_pos": None,
        "cod_pos": None,
    }


PRIMARY_RADIUS_M = 3218  # meters (~2 miles)
SECONDARY_RADIUS_M = 4828  # meters (~3 miles)
INITIAL_COMPARABLE_LIMIT = 7
EXTENDED_COMPARABLE_LIMIT = 15


def _decimal_to_str(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _deserialize_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _serialize_date(value: Optional[dt.date]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def _deserialize_date(value: Any) -> Optional[dt.date]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _centroid_lat_lon(geom) -> Tuple[Optional[float], Optional[float]]:
    """
    Grab a representative latitude/longitude from the geometry or its centroid.
    """
    if geom is None:
        return None, None
    centroid = getattr(geom, "centroid", None)
    if centroid is not None:
        return getattr(centroid, "y", None), getattr(centroid, "x", None)
    return getattr(geom, "y", None), getattr(geom, "x", None)


def _snapshot_payload(snapshot: cma.PropertySnapshot) -> Dict[str, Any]:
    metadata = dict(snapshot.metadata) if isinstance(snapshot.metadata, dict) else {}
    lat = getattr(snapshot, "latitude", None)
    lon = getattr(snapshot, "longitude", None)
    if lat is None or lon is None:
        lat, lon = _centroid_lat_lon(snapshot.geom)
    if (lat is None or lon is None) and hasattr(snapshot, "display_point"):
        point = snapshot.display_point()
        if point is not None:
            lat = getattr(point, "y", None)
            lon = getattr(point, "x", None)
    return {
        "parcel_number": snapshot.parcel_number,
        "address": snapshot.address,
        "sale_price": _decimal_to_str(snapshot.sale_price),
        "sale_date": _serialize_date(snapshot.sale_date),
        "property_type": snapshot.property_type,
        "living_area": _decimal_to_str(snapshot.living_area),
        "lot_acres": _decimal_to_str(snapshot.lot_acres),
        "bedrooms": _decimal_to_str(snapshot.bedrooms),
        "bathrooms": _decimal_to_str(snapshot.bathrooms),
        "year_built": snapshot.year_built,
        "effective_year_built": snapshot.effective_year_built,
        "garage_sqft": _decimal_to_str(snapshot.garage_sqft),
        "acres": _decimal_to_str(snapshot.acres),
        "assessed_value": _decimal_to_str(snapshot.assessed_value),
        "metadata": metadata,
        "latitude": lat,
        "longitude": lon,
    }


def _score_payload(score: Optional[cma.ComparableScore]) -> Optional[Dict[str, Any]]:
    if score is None:
        return None
    return {
        "location_score": _decimal_to_str(score.location_score),
        "time_score": _decimal_to_str(score.time_score),
        "physical_score": _decimal_to_str(score.physical_score),
        "total_score": _decimal_to_str(score.total_score),
    }


def _comparable_payload(comp: cma.ComparableResult) -> Dict[str, Any]:
    return {
        "snapshot": _snapshot_payload(comp.snapshot),
        "sale_price": _decimal_to_str(comp.sale_price),
        "sale_date": _serialize_date(comp.sale_date),
        "assessed_value": _decimal_to_str(comp.assessed_value),
        "distance_meters": _float_or_none(comp.distance_meters),
        "distance_miles": _decimal_to_str(comp.distance_miles),
        "difference_flags": comp.difference_flags,
        "inclusion_rank": comp.inclusion_rank,
        "score": _score_payload(comp.score),
    }


def _snapshot_from_payload(payload: Dict[str, Any]) -> cma.PropertySnapshot:
    metadata = dict(payload.get("metadata") or {})
    latitude = _float_or_none(payload.get("latitude"))
    longitude = _float_or_none(payload.get("longitude"))
    geom = None
    if latitude is not None and longitude is not None:
        try:
            geom = Point(longitude, latitude, srid=4326)
        except (TypeError, ValueError):
            geom = None
    if latitude is not None:
        metadata.setdefault("latitude", latitude)
    if longitude is not None:
        metadata.setdefault("longitude", longitude)
    return cma.PropertySnapshot(
        parcel_number=payload.get("parcel_number") or "",
        address=payload.get("address") or "",
        sale_price=_deserialize_decimal(payload.get("sale_price")),
        sale_date=_deserialize_date(payload.get("sale_date")),
        property_type=payload.get("property_type"),
        living_area=_deserialize_decimal(payload.get("living_area")),
        lot_acres=_deserialize_decimal(payload.get("lot_acres")),
        bedrooms=_deserialize_decimal(payload.get("bedrooms")),
        bathrooms=_deserialize_decimal(payload.get("bathrooms")),
        year_built=_int_or_none(payload.get("year_built")),
        effective_year_built=_int_or_none(payload.get("effective_year_built")),
        garage_sqft=_deserialize_decimal(payload.get("garage_sqft")),
        acres=_deserialize_decimal(payload.get("acres")),
        assessed_value=_deserialize_decimal(payload.get("assessed_value")),
        geom=geom,
        latitude=latitude,
        longitude=longitude,
        metadata=metadata,
    )


def _score_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[cma.ComparableScore]:
    if not isinstance(payload, dict):
        return None
    location = _deserialize_decimal(payload.get("location_score"))
    time_score = _deserialize_decimal(payload.get("time_score"))
    physical = _deserialize_decimal(payload.get("physical_score"))
    total = _deserialize_decimal(payload.get("total_score"))
    if location is None and time_score is None and physical is None:
        return None
    return cma.ComparableScore(
        location_score=location or Decimal("0"),
        time_score=time_score or Decimal("0"),
        physical_score=physical or Decimal("0"),
        total_score=total or Decimal("0"),
    )


def _comparable_from_payload(payload: Dict[str, Any]) -> cma.ComparableResult:
    return cma.ComparableResult(
        snapshot=_snapshot_from_payload(payload.get("snapshot") or {}),
        sale_price=_deserialize_decimal(payload.get("sale_price")),
        sale_date=_deserialize_date(payload.get("sale_date")),
        assessed_value=_deserialize_decimal(payload.get("assessed_value")),
        distance_meters=_float_or_none(payload.get("distance_meters")),
        distance_miles=_deserialize_decimal(payload.get("distance_miles")),
        difference_flags=payload.get("difference_flags") or {},
        inclusion_rank=_int_or_none(payload.get("inclusion_rank")) or 0,
        score=_score_from_payload(payload.get("score")),
    )


def _coerce_percent(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1]
        return float(text)
    except (TypeError, ValueError):
        return None


def extract_assessment_change_pct(metadata: Any) -> Optional[float]:
    if not isinstance(metadata, dict):
        return None
    candidate_keys = (
        "assessed_change_pct",
        "assessment_change_pct",
        "percent_change",
        "percentchange",
        "pct_change",
        "pct change",
        "change_pct",
    )
    for key in candidate_keys:
        if key in metadata:
            pct = _coerce_percent(metadata.get(key))
            if pct is not None:
                return pct
    assessor_meta = metadata.get("assessor")
    if isinstance(assessor_meta, dict):
        for key in candidate_keys:
            pct = _coerce_percent(assessor_meta.get(key))
            if pct is not None:
                return pct
    return None


def load_subject_with_roll_context(parcel_number: str) -> Tuple[cma.PropertySnapshot, int]:
    try:
        subject = cma.load_subject(parcel_number)
    except ValueError as exc:
        logger.warning("Appeal helper failed to load parcel %s: %s", parcel_number, exc)
        raise

    active_roll_year = timezone.now().year
    metadata = subject.metadata if isinstance(subject.metadata, dict) else {}
    metadata["assessment_roll_year"] = active_roll_year
    assessor_meta = metadata.setdefault("assessor", {})
    assessor_meta["assessment_year"] = active_roll_year
    assessed_value = subject.assessed_value or _to_decimal_safe(metadata.get("assessed_value"))
    if assessed_value is not None:
        assessor_meta["assessed_value"] = float(assessed_value)
    else:
        assessor_meta.pop("assessed_value", None)
    assessor_meta.pop("prior_assessment_year", None)
    assessor_meta.pop("prior_assessed_value", None)
    assessor_meta.pop("assessment_change_pct", None)
    metadata.pop("assessed_change_pct", None)
    subject.metadata = metadata
    return subject, active_roll_year

def _resolve_neighborhood_context(raw_code: Optional[str]) -> Dict[str, Any]:
    """
    Prefer official 2025 metrics, falling back to the most recent data if necessary.
    """
    snapshot = get_neighborhood_snapshot(raw_code, year=2025)
    if not snapshot:
        snapshot = get_neighborhood_snapshot(raw_code)
    return snapshot or _empty_neighborhood_snapshot(raw_code)


def _subject_neighborhood_code(subject: cma.PropertySnapshot) -> Optional[str]:
    metadata = subject.metadata if isinstance(subject.metadata, dict) else {}
    raw_neighborhood = metadata.get("neighborhood_code")
    if not raw_neighborhood:
        assessor_meta = metadata.get("assessor") if isinstance(metadata, dict) else None
        if isinstance(assessor_meta, dict):
            raw_neighborhood = assessor_meta.get("neighborhoodcode") or assessor_meta.get("neighborhood_code")
    if not raw_neighborhood:
        raw_neighborhood = metadata.get("neighborhood")
    return raw_neighborhood


def get_subject_neighborhood_snapshot(subject: cma.PropertySnapshot) -> Dict[str, Any]:
    raw_code = _subject_neighborhood_code(subject)
    return _resolve_neighborhood_context(raw_code)


def _comparable_candidates(subject: cma.PropertySnapshot, limit: int) -> Tuple[List[cma.ComparableResult], float]:
    result = build_sales_comps_v2(
        subject,
        limit=limit,
        months=DEFAULT_LOOKBACK_MONTHS,
        base_radius_m=PRIMARY_RADIUS_M,
        max_radius_m=SECONDARY_RADIUS_M,
    )
    return result.comparables, result.radius_meters_used


def choose_citizen_comps(
    subject: cma.PropertySnapshot,
    *,
    months: int = DEFAULT_LOOKBACK_MONTHS,
    limit: int = 5,
    radius_meters: float = 8000,
) -> List[cma.ComparableResult]:
    """
    Reuse the existing CMA pipeline but default to very simple, citizen-friendly constraints:
      • last N months (default 18)
      • closest by distance
      • take top 3–5 results

    Post-filter to prefer comps within ~1 mile when distance is available.
    """

    result = build_sales_comps_v2(
        subject,
        limit=max(limit, 8),  # fetch a few extra to allow post-filtering
        months=months,
        base_radius_m=radius_meters,
        max_radius_m=radius_meters,
    )
    comps = result.comparables

    within_one_mile = [c for c in comps if (c.distance_miles or Decimal("0")) <= Decimal("1.0")]
    shortlisted = within_one_mile[:limit] if len(within_one_mile) >= 3 else comps[:limit]
    logger.info(
        "Citizen comps subject=%s total=%s within_one_mile=%s limit=%s radius=%s",
        subject.parcel_number,
        len(comps),
        len(within_one_mile),
        limit,
        radius_meters,
    )
    return shortlisted


def _median(values: List[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / Decimal("2")


def compute_over_assessment(subject_assessed: Optional[Decimal], comparable_prices: List[Decimal]) -> Tuple[Optional[float], Optional[int]]:
    """
    Return (percent_over, comp_count) comparing assessed value to the median comp sale price.
    Positive means assessed > market estimate. Percent as +X% if over-assessed.
    """
    comp_len = len(comparable_prices)
    if subject_assessed in (None, Decimal("0")):
        return None, comp_len
    median_adj = _median(comparable_prices)
    if median_adj in (None, Decimal("0")):
        return None, comp_len
    try:
        diff = (Decimal(str(subject_assessed)) - Decimal(str(median_adj))) / Decimal(str(median_adj)) * Decimal("100")
        return float(diff), comp_len
    except Exception:
        return None, comp_len


def score_appeal(
    *,
    over_assessment_pct: Optional[float],
    comp_count: int,
    neigh_diff_pct: Optional[float],
    neigh_reliability: Optional[str],
    cod: Optional[float],
) -> Tuple[int, str, List[str]]:
    """
    Produce a 0–100 score plus rating label and reasons.
    Heuristic, citizen-first, aligned to described factors.
    """
    score = 50
    reasons: List[str] = []

    # Over-assessment weight
    if over_assessment_pct is not None:
        if over_assessment_pct >= 20:
            score += 25
            reasons.append("Assessed value appears 20%+ above market comps.")
        elif over_assessment_pct >= 12:
            score += 18
            reasons.append("Assessed value ~12–20% above market comps.")
        elif over_assessment_pct >= 7:
            score += 10
            reasons.append("Assessed value ~7–12% above market comps.")
        elif over_assessment_pct <= 0:
            score -= 20
            reasons.append("Assessed value is at or below market comps.")
        else:
            score += 2
            reasons.append("Slightly above comps; may be marginal.")

    # Comparable depth/quality
    if comp_count >= 5:
        score += 10
        reasons.append("5+ recent nearby comparable sales found.")
    elif comp_count >= 3:
        score += 5
        reasons.append("3–4 nearby comparable sales found.")
    else:
        score -= 15
        reasons.append("Fewer than 3 strong comparables available.")

    # Neighborhood differential
    if neigh_diff_pct is not None:
        if neigh_diff_pct >= 8:
            score += 12
            reasons.append("Your assessment rose far more than your neighborhood average.")
        elif neigh_diff_pct >= 4:
            score += 6
            reasons.append("Your assessment rose more than the neighborhood average.")
        elif neigh_diff_pct <= 0:
            score -= 10
            reasons.append("Your assessment did not rise more than neighbors.")

    # Reliability and COD
    if neigh_reliability == "LOW":
        score += 6
        reasons.append("Neighborhood sample is small or inconsistent (higher COD).")
    elif neigh_reliability == "HIGH":
        score -= 4
        reasons.append("Neighborhood sample is large with consistent assessments (low COD).")

    if cod is not None:
        if cod >= 18:
            score += 6
        elif cod <= 8:
            score -= 2

    # Clamp and label
    score = max(0, min(100, score))
    if score >= 80:
        label = "Very Strong"
    elif score >= 65:
        label = "Strong"
    elif score >= 50:
        label = "Moderate"
    else:
        label = "Weak"
    return score, label, reasons[:4]


def citizen_assessment_summary(
    subject: cma.PropertySnapshot,
    *,
    comparables: Optional[List[cma.ComparableResult]] = None,
    radius_meters: float = 8000,
    limit: int = 5,
) -> Dict[str, Any]:
    """
    High-level wrapper to compute: comps, neighborhood context, over-assessment, and score.
    """
    comps = comparables or choose_citizen_comps(
        subject, radius_meters=radius_meters, limit=limit
    )
    comparable_prices = [c.sale_price for c in comps]
    subject_assessed = subject.assessed_value or _to_decimal_safe(subject.metadata.get("assessed_value"))
    over_pct, comp_count = compute_over_assessment(subject_assessed, comparable_prices)

    neigh = get_subject_neighborhood_snapshot(subject)

    # We generally cannot compute "your increase vs neighborhood" without prior-year assessed.
    # Leave as None unless a custom field is passed via metadata in the future.
    your_vs_neigh = None

    score, label, reasons = score_appeal(
        over_assessment_pct=over_pct,
        comp_count=comp_count or 0,
        neigh_diff_pct=your_vs_neigh,
        neigh_reliability=neigh.get("reliability"),
        cod=neigh.get("cod"),
    )

    return {
        "comparables": comps,
        "over_assessment_pct": over_pct,
        "comp_count": comp_count,
        "neighborhood": neigh,
        "neigh_diff_pct": your_vs_neigh,
        "score": score,
        "rating": label,
        "reasons": reasons,
    }


def _to_decimal_safe(value: Any) -> Optional[Decimal]:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except Exception:
        return None
