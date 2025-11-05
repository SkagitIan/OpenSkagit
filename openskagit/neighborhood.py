import re
from typing import Any, Dict, List, Optional

from django.http import Http404
from django.shortcuts import render

from openskagit.models import NeighborhoodMetrics


_CODE_PATTERN = re.compile(r"\(([A-Z0-9]+)\)")


def clamp(value: float, min_value: float, max_value: float) -> float:
    """Keep numeric values within gauge range (0–100%)."""
    return max(min_value, min(value, max_value))


def _candidate_codes(raw_code: str) -> List[str]:
    """
    Generate plausible neighborhood code candidates based on how assessor data tends to be formatted.
    """
    text = str(raw_code or "").strip()
    if not text:
        return []

    candidates: List[str] = []
    upper = text.upper()
    candidates.append(upper)

    match = _CODE_PATTERN.search(upper)
    if match:
        candidates.append(match.group(1))

    # Grab first token (e.g., "20ASKY - Conway" -> "20ASKY")
    first_token = re.split(r"[\s\-/]+", upper)[0]
    if first_token:
        candidates.append(first_token)

    # Remove duplicates while preserving order
    seen = set()
    ordered: List[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def build_snapshot_context(metrics: NeighborhoodMetrics) -> Dict[str, Any]:
    """
    Build a rich neighborhood snapshot payload with gauge positions and display helpers.
    """
    ratio_value: Optional[float] = None
    if metrics.sales_ratio is not None:
        ratio_value = metrics.sales_ratio / 100.0

    if ratio_value is not None:
        sales_ratio_pos = clamp(((ratio_value - 0.8) / 0.4) * 100, 0, 100)
    else:
        sales_ratio_pos = None

    if metrics.prd is not None:
        prd_pos = clamp(((metrics.prd - 0.90) / 0.20) * 100, 0, 100)
    else:
        prd_pos = None

    if metrics.cod is not None:
        cod_pos = clamp((metrics.cod / 40) * 100, 0, 100)
    else:
        cod_pos = None

    median_ratio_pct = metrics.median_ratio * 100 if metrics.median_ratio is not None else None

    reliability_raw = (metrics.reliability or "").strip()
    reliability_display = reliability_raw or "Unknown"
    reliability_code = reliability_display.upper()

    # Standardize reliability buckets for the scoring helper.
    normalized_reliability = None
    if reliability_code in {"HIGH", "MEDIUM", "LOW"}:
        normalized_reliability = reliability_code
    else:
        normalized_reliability = None

    if normalized_reliability is None and metrics.sample_size and metrics.cod is not None:
        # Mirror the earlier heuristic if reliability was not set.
        if metrics.sample_size >= 30 and metrics.cod < 10:
            normalized_reliability = "HIGH"
        elif metrics.sample_size >= 15 and metrics.cod < 15:
            normalized_reliability = "MEDIUM"
        else:
            normalized_reliability = "LOW"
        reliability_display = normalized_reliability.title()

    sample_size_pct = getattr(metrics, "sample_size_pct", None)

    return {
        "code": metrics.neighborhood_code,
        "name": getattr(metrics, "name", None),
        "year": metrics.year,
        "avg_increase_pct": getattr(metrics, "avg_change_pct", None),
        "cod": metrics.cod,
        "valid_sales": metrics.sample_size,
        "parcels": getattr(metrics, "parcels", None),
        "reliability": normalized_reliability or reliability_display.upper(),
        "reliability_display": reliability_display,
        "sales_ratio": metrics.sales_ratio,
        "median_ratio": metrics.median_ratio,
        "median_ratio_pct": median_ratio_pct,
        "prior_sales_ratio": getattr(metrics, "prior_sales_ratio", None),
        "sales_ratio_delta": None,
        "prior_cod": getattr(metrics, "prior_cod", None),
        "prd": metrics.prd,
        "prior_prd": getattr(metrics, "prior_prd", None),
        "sample_size_pct": sample_size_pct,
        # UI helpers
        "sales_ratio_pos": round(sales_ratio_pos, 1) if sales_ratio_pos is not None else None,
        "prd_pos": round(prd_pos, 1) if prd_pos is not None else None,
        "cod_pos": round(cod_pos, 1) if cod_pos is not None else None,
    }


def get_neighborhood_snapshot(raw_code: Optional[str], *, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch the most relevant NeighborhoodMetrics record for the supplied identifier.
    """
    if not raw_code:
        return None

    for candidate in _candidate_codes(raw_code):
        query = NeighborhoodMetrics.objects.filter(neighborhood_code=candidate)
        if year:
            query = query.filter(year=year)
        metrics = query.order_by("-year").first()
        if metrics:
            snapshot = build_snapshot_context(metrics)
            # Enrich with delta information if we have a prior observation.
            prior = (
                NeighborhoodMetrics.objects.filter(
                    neighborhood_code=metrics.neighborhood_code,
                    year__lt=metrics.year,
                )
                .order_by("-year")
                .first()
            )
            if prior and snapshot.get("sales_ratio") is not None and prior.sales_ratio is not None:
                snapshot["prior_sales_ratio"] = prior.sales_ratio
                snapshot["sales_ratio_delta"] = snapshot["sales_ratio"] - prior.sales_ratio
            if prior and snapshot.get("cod") is not None and prior.cod is not None:
                snapshot["prior_cod"] = prior.cod
            if prior and snapshot.get("prd") is not None and prior.prd is not None:
                snapshot["prior_prd"] = prior.prd
            return snapshot

    return None


def neighborhood_snapshot_view(request, code: str):
    """
    Renders the neighborhood snapshot dashboard.
    Example URL: /neighborhoods/20ASKY/
    """
    year_param = request.GET.get("year")
    year: Optional[int] = None
    if year_param:
        try:
            year = int(year_param)
        except (TypeError, ValueError):
            year = None

    snapshot = get_neighborhood_snapshot(code, year=year)
    if not snapshot:
        raise Http404("Neighborhood metrics not found.")
    context = {"neighborhood": snapshot}
    return render(request, "openskagit/neighborhood_snapshot.html", context)
