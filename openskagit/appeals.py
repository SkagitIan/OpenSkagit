from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.core.cache import cache
from django.utils import timezone

from . import cma
from .models import AssessmentRoll, Assessor
from .neighborhood import get_neighborhood_snapshot


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
COMPARABLES_CACHE_TTL = 5 * 60


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


def current_assessment_year() -> int:
    year = (
        AssessmentRoll.objects.order_by("-year")
        .values_list("year", flat=True)
        .first()
    )
    if year is None:
        return timezone.now().year
    return int(year)


def load_subject_with_roll_context(parcel_number: str) -> Tuple[cma.PropertySnapshot, int]:
    current_roll_year = current_assessment_year()
    active_roll_year = current_roll_year
    try:
        subject = cma.load_subject(parcel_number, roll_year=current_roll_year)
    except ValueError as exc:
        logger.warning(
            "Appeal helper failed to load parcel %s for roll %s: %s",
            parcel_number,
            current_roll_year,
            exc,
        )
        try:
            subject = cma.load_subject(parcel_number)
        except ValueError:
            raise exc

        fallback_year: Optional[int] = None
        metadata_for_year = subject.metadata if isinstance(subject.metadata, dict) else {}
        raw_year = metadata_for_year.get("assessment_roll_year")
        if raw_year is not None:
            try:
                fallback_year = int(raw_year)
            except (TypeError, ValueError):
                fallback_year = None
        if fallback_year is None:
            assessor_meta = metadata_for_year.get("assessor") if isinstance(metadata_for_year, dict) else None
            if isinstance(assessor_meta, dict):
                raw_year = assessor_meta.get("assessment_year") or assessor_meta.get("year")
                if raw_year is not None:
                    try:
                        fallback_year = int(raw_year)
                    except (TypeError, ValueError):
                        fallback_year = None
        if fallback_year is not None:
            active_roll_year = fallback_year
            if fallback_year != current_roll_year:
                logger.info(
                    "Appeal helper using roll %s for parcel %s (current roll %s unavailable)",
                    fallback_year,
                    parcel_number,
                    current_roll_year,
                )

    metadata = subject.metadata if isinstance(subject.metadata, dict) else {}
    metadata["assessment_roll_year"] = active_roll_year

    assessor_row = (
        Assessor.objects.select_related("roll")
        .filter(parcel_number=parcel_number, roll__year=active_roll_year)
        .first()
    )
    if assessor_row:
        metadata["assessed_value"] = assessor_row.assessed_value

    prior_roll_year = active_roll_year - 1
    prior_assessor = (
        Assessor.objects.select_related("roll")
        .filter(parcel_number=parcel_number, roll__year=prior_roll_year)
        .first()
        if prior_roll_year > 0
        else None
    )

    assessor_meta = metadata.setdefault("assessor", {})
    if assessor_row:
        assessor_meta["assessment_year"] = active_roll_year
        assessor_meta["assessed_value"] = assessor_row.assessed_value
    if prior_assessor:
        assessor_meta["prior_assessment_year"] = prior_roll_year
        assessor_meta["prior_assessed_value"] = prior_assessor.assessed_value

    assessed_change_pct: Optional[float] = None
    if assessor_row and prior_assessor:
        current_value = assessor_row.assessed_value
        prior_value = prior_assessor.assessed_value
        if current_value is not None and prior_value not in (None, 0):
            try:
                current_dec = Decimal(str(current_value))
                prior_dec = Decimal(str(prior_value))
            except (InvalidOperation, TypeError):
                current_dec = None
                prior_dec = None
            if current_dec is not None and prior_dec not in (None, Decimal("0")):
                try:
                    change_pct = (current_dec - prior_dec) / prior_dec * Decimal("100")
                    assessed_change_pct = float(change_pct)
                except (InvalidOperation, ZeroDivisionError):
                    assessed_change_pct = None

    if assessed_change_pct is not None:
        metadata["assessed_change_pct"] = assessed_change_pct
        assessor_meta["assessment_change_pct"] = assessed_change_pct

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


def _subject_roll_year(subject: cma.PropertySnapshot) -> Optional[int]:
    metadata = subject.metadata if isinstance(subject.metadata, dict) else {}
    roll_year = metadata.get("assessment_roll_year")
    if roll_year is None:
        assessor_meta = metadata.get("assessor") if isinstance(metadata, dict) else None
        if isinstance(assessor_meta, dict):
            roll_year = assessor_meta.get("assessment_year") or assessor_meta.get("year")
    try:
        return int(roll_year) if roll_year is not None else None
    except (TypeError, ValueError):
        return None


def get_subject_neighborhood_snapshot(subject: cma.PropertySnapshot) -> Dict[str, Any]:
    raw_code = _subject_neighborhood_code(subject)
    return _resolve_neighborhood_context(raw_code)


def _months_ago(months: int) -> dt.date:
    today = dt.date.today()
    year = today.year
    month = max(1, today.month - months)
    # naive month subtraction; adequate for our filter window
    return dt.date(year if month <= today.month else year - 1, month, 1)


def _cache_key_for_comps(subject: cma.PropertySnapshot, radius_meters: float, limit: int) -> str:
    roll_year = _subject_roll_year(subject) or 0
    return f"appeal_comps:{subject.parcel_number}:{roll_year}:{int(radius_meters)}:{limit}"


def _cached_comparables(subject: cma.PropertySnapshot, radius_meters: float, limit: int) -> List[cma.ComparableResult]:
    key = _cache_key_for_comps(subject, radius_meters, limit)
    comps = cache.get(key)
    if comps is None:
        comps = choose_citizen_comps(subject, radius_meters=radius_meters, limit=limit)
        cache.set(key, comps, COMPARABLES_CACHE_TTL)
    return comps


def _comparable_candidates(subject: cma.PropertySnapshot, limit: int) -> Tuple[List[cma.ComparableResult], float]:
    comps = _cached_comparables(subject, PRIMARY_RADIUS_M, limit)
    radius_used = PRIMARY_RADIUS_M
    if len(comps) < 4:
        comps = _cached_comparables(subject, SECONDARY_RADIUS_M, limit)
        radius_used = SECONDARY_RADIUS_M
    return comps, radius_used


def choose_citizen_comps(
    subject: cma.PropertySnapshot,
    *,
    months: int = 6,
    limit: int = 5,
    radius_meters: float = 8000,
) -> List[cma.ComparableResult]:
    """
    Reuse the existing CMA pipeline but default to very simple, citizen-friendly constraints:
      • last N months (default 6)
      • closest by distance
      • take top 3–5 results

    Post-filter to prefer comps within ~1 mile when distance is available.
    """

    filters = cma.CmaFilters(
        sale_date_min=_months_ago(months),
        sale_date_max=None,
        property_type=None,
    )
    comp = cma.build_comparables(
        subject=subject,
        filters=filters,
        excluded=[],
        sort_field="distance",
        sort_direction="asc",
        limit=max(limit, 8),  # fetch a few extra to allow post-filtering
        radius_meters=radius_meters,
        load_improvements=False,
    )
    comps = comp.comparables

    within_one_mile = [c for c in comps if (c.distance_miles or Decimal("0")) <= Decimal("1.0")]
    shortlisted = within_one_mile[:limit] if len(within_one_mile) >= 3 else comps[:limit]
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
    if subject_assessed in (None, Decimal("0")):
        return None, None
    median_adj = _median(comparable_prices)
    if median_adj in (None, Decimal("0")):
        return None, len(comparable_prices)
    try:
        diff = (Decimal(str(subject_assessed)) - Decimal(str(median_adj))) / Decimal(str(median_adj)) * Decimal("100")
        return float(diff), len(comparable_prices)
    except Exception:
        return None, len(comparable_prices)


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
