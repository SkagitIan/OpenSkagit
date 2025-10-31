from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

from . import cma


@dataclass(frozen=True)
class NeighborhoodStats:
    code: str
    name: Optional[str]
    avg_change_pct: Optional[float]
    cod: Optional[float]
    valid_sales: Optional[int]
    parcels: Optional[int]


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace("%", "")
        if text == "":
            return None
        return float(text)
    except Exception:
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if text == "":
            return None
        return int(float(text))
    except Exception:
        return None


def load_ratio_stats() -> Dict[str, NeighborhoodStats]:
    """
    Load neighborhood ratio summary stats from a JSON or PDF path.

    Configuration options (first match wins):
      • settings.RATIO_SUMMARY_JSON – path to a JSON file containing records like
        {"code": "20MVCENTRL", "name": "Mount Vernon Central", "pct_change": 2.6, "cod": 8.9, "valid_sales": 42, "parcels": 1800}
      • settings.RATIO_SUMMARY_PDF – path to the provided county PDF. If pdfplumber
        is installed, we will attempt a best-effort table extraction.

    Returns a dict keyed by neighborhood code.
    """

    results: Dict[str, NeighborhoodStats] = {}

    # Try JSON first (simplest and most reliable)
    json_path = getattr(settings, "RATIO_SUMMARY_JSON", None)
    if json_path:
        path = Path(str(json_path))
        if path.exists():
            import json

            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh) or []
            for row in data:
                code = (row.get("code") or "").strip()
                if not code:
                    continue
                results[code] = NeighborhoodStats(
                    code=code,
                    name=(row.get("name") or None),
                    avg_change_pct=_as_float(row.get("pct_change")),
                    cod=_as_float(row.get("cod")),
                    valid_sales=_as_int(row.get("valid_sales")),
                    parcels=_as_int(row.get("parcels")),
                )
            return results

    # Fallback: try to parse the PDF if pdfplumber is available
    pdf_path = getattr(settings, "RATIO_SUMMARY_PDF", None)
    if pdf_path:
        try:
            import pdfplumber  # type: ignore

            path = Path(str(pdf_path))
            if path.exists():
                with pdfplumber.open(str(path)) as pdf:
                    for page in pdf.pages:
                        tables = page.extract_tables() or []
                        for table in tables:
                            # Heuristic: try to find columns matching expected headers
                            # and coerce records. The exact structure may vary, so be lenient.
                            headers: List[str] = [str(h or "").strip().lower() for h in (table[0] or [])]
                            rows = table[1:]
                            # Map header indices
                            def col_index(*aliases: str) -> Optional[int]:
                                for a in aliases:
                                    if a in headers:
                                        return headers.index(a)
                                return None

                            idx_code = col_index("neighborhood", "code")
                            idx_name = col_index("name", "neighborhood name")
                            idx_pct = col_index("% change", "%change", "pct change")
                            idx_cod = col_index("cod")
                            idx_sales = col_index("valid sales", "valid")
                            idx_parcels = col_index("parcels", "parcel count")

                            if idx_code is None:
                                continue

                            for r in rows:
                                try:
                                    code = (r[idx_code] or "").strip()
                                except Exception:
                                    continue
                                if not code:
                                    continue
                                name = None
                                if idx_name is not None:
                                    try:
                                        name = (r[idx_name] or None)
                                    except Exception:
                                        name = None
                                stats = NeighborhoodStats(
                                    code=code,
                                    name=name,
                                    avg_change_pct=_as_float(r[idx_pct]) if idx_pct is not None else None,
                                    cod=_as_float(r[idx_cod]) if idx_cod is not None else None,
                                    valid_sales=_as_int(r[idx_sales]) if idx_sales is not None else None,
                                    parcels=_as_int(r[idx_parcels]) if idx_parcels is not None else None,
                                )
                                results[code] = stats
        except ModuleNotFoundError:
            # pdfplumber not installed; return empty results
            pass
        except Exception:
            # Best-effort parse; ignore failures
            pass

    return results


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


def neighborhood_context(neighborhood_code: Optional[str], stats: Dict[str, NeighborhoodStats]) -> Dict[str, Any]:
    rec = stats.get(neighborhood_code or "") if stats else None
    reliability: Optional[str] = None
    if rec and rec.valid_sales is not None and rec.cod is not None:
        if rec.valid_sales >= 30 and rec.cod < 10:
            reliability = "HIGH"
        elif rec.valid_sales >= 15 and rec.cod < 15:
            reliability = "MEDIUM"
        else:
            reliability = "LOW"
    return {
        "code": neighborhood_code,
        "name": getattr(rec, "name", None) if rec else None,
        "avg_increase_pct": getattr(rec, "avg_change_pct", None) if rec else None,
        "cod": getattr(rec, "cod", None) if rec else None,
        "valid_sales": getattr(rec, "valid_sales", None) if rec else None,
        "parcels": getattr(rec, "parcels", None) if rec else None,
        "reliability": reliability,
    }


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

    ratio_stats = load_ratio_stats()
    neigh = neighborhood_context(subject.metadata.get("neighborhood_code"), ratio_stats)

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

