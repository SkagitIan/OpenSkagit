from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from . import cma
from .neighborhood import get_neighborhood_snapshot


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


def _resolve_neighborhood_context(raw_code: Optional[str]) -> Dict[str, Any]:
    """
    Prefer official 2025 metrics, falling back to the most recent data if necessary.
    """
    snapshot = get_neighborhood_snapshot(raw_code, year=2025)
    if not snapshot:
        snapshot = get_neighborhood_snapshot(raw_code)
    return snapshot or _empty_neighborhood_snapshot(raw_code)


def _months_ago(months: int) -> dt.date:
    today = dt.date.today()
    year = today.year
    month = max(1, today.month - months)
    # naive month subtraction; adequate for our filter window
    return dt.date(year if month <= today.month else year - 1, month, 1)


def choose_citizen_comps(subject: cma.PropertySnapshot, *, months: int = 6, limit: int = 5) -> List[cma.ComparableResult]:
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
        manual_adjustments={},
        excluded=[],
        sort_field="distance",
        sort_direction="asc",
        limit=max(limit, 8),  # fetch a few extra to allow post-filtering
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


def compute_over_assessment(subject_assessed: Optional[Decimal], adjusted_comp_prices: List[Decimal]) -> Tuple[Optional[float], Optional[int]]:
    """
    Return (percent_over, comp_count) comparing assessed value to median adjusted comp price.
    Positive means assessed > market estimate. Percent as +X% if over-assessed.
    """
    if subject_assessed in (None, Decimal("0")):
        return None, None
    median_adj = _median(adjusted_comp_prices)
    if median_adj in (None, Decimal("0")):
        return None, len(adjusted_comp_prices)
    try:
        diff = (Decimal(str(subject_assessed)) - Decimal(str(median_adj))) / Decimal(str(median_adj)) * Decimal("100")
        return float(diff), len(adjusted_comp_prices)
    except Exception:
        return None, len(adjusted_comp_prices)


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


def citizen_assessment_summary(subject: cma.PropertySnapshot) -> Dict[str, Any]:
    """
    High-level wrapper to compute: comps, neighborhood context, over-assessment, and score.
    """
    comps = choose_citizen_comps(subject)
    adjusted_prices = [c.adjusted_price for c in comps]
    over_pct, comp_count = compute_over_assessment(_to_decimal_safe(subject.metadata.get("assessed_value")) or _to_decimal_safe(None), adjusted_prices)
    # Try to derive assessed from Assessor attributes too if not present in metadata
    if over_pct is None and subject.metadata:
        assessed_value = _to_decimal_safe(subject.metadata.get("assessed_value"))
        if assessed_value is not None:
            over_pct, comp_count = compute_over_assessment(assessed_value, adjusted_prices)

    metadata = subject.metadata or {}
    raw_neighborhood = metadata.get("neighborhood_code")
    if not raw_neighborhood:
        assessor_meta = metadata.get("assessor") if isinstance(metadata, dict) else None
        if isinstance(assessor_meta, dict):
            raw_neighborhood = assessor_meta.get("neighborhoodcode") or assessor_meta.get("neighborhood_code")
    if not raw_neighborhood:
        raw_neighborhood = metadata.get("neighborhood")

    neigh = _resolve_neighborhood_context(raw_neighborhood)

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
