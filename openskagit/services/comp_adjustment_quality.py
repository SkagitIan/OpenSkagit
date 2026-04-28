from __future__ import annotations

from typing import Any, Dict, Optional, Sequence


PRIMARY_NET_ADJ_MAX = 0.10
PRIMARY_GROSS_ADJ_MAX = 0.15
FLAG_NET_ADJ_THRESHOLD = 0.15
FLAG_GROSS_ADJ_THRESHOLD = 0.25
FLAG_DOMINANT_SHARE_THRESHOLD = 0.70
FLAG_SIZE_GAP_THRESHOLD = 0.25

PENALTY_BY_FLAG = {
    "high_gross_adjustment_pct": 18,
    "high_net_adjustment_pct": 14,
    "large_size_gap": 14,
    "dominant_living_area_adjustment": 10,
    "dominant_age_adjustment": 4,
    "dominant_time_adjustment": 3,
    "dominant_lot_adjustment": 3,
    "dominant_garage_adjustment": 2,
}
MAX_PENALTY_POINTS = 35


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def compute_adjustment_quality_metrics(
    *,
    sale_price: Optional[float],
    total_adjustment: Optional[float],
    adjustments: Sequence[Dict[str, Any]],
    subject_living_area: Optional[float],
    comp_living_area: Optional[float],
    primary_net_max: float = PRIMARY_NET_ADJ_MAX,
    primary_gross_max: float = PRIMARY_GROSS_ADJ_MAX,
    flag_net_threshold: float = FLAG_NET_ADJ_THRESHOLD,
    flag_gross_threshold: float = FLAG_GROSS_ADJ_THRESHOLD,
    flag_dominant_share_threshold: float = FLAG_DOMINANT_SHARE_THRESHOLD,
    flag_size_gap_threshold: float = FLAG_SIZE_GAP_THRESHOLD,
) -> Dict[str, Any]:
    parsed_sale_price = _safe_float(sale_price)
    parsed_total_adj = _safe_float(total_adjustment)
    if parsed_sale_price is None or parsed_sale_price <= 0:
        return {
            "group": "support",
            "group_reasons": ["invalid_sale_price"],
            "flags": ["invalid_sale_price"],
            "penalty_points": 0,
            "net_adjustment_pct": None,
            "gross_adjustment_pct": None,
            "dominant_factor": None,
            "dominant_share": None,
            "size_gap_pct": None,
        }

    gross_adjustment = 0.0
    dominant_amount = 0.0
    dominant_factor: Optional[str] = None
    for item in adjustments or []:
        amount = _safe_float(item.get("amount"))
        if amount is None:
            continue
        gross_adjustment += abs(amount)
        if abs(amount) > dominant_amount:
            dominant_amount = abs(amount)
            dominant_factor = str(item.get("key") or "").strip() or None

    if parsed_total_adj is None:
        parsed_total_adj = 0.0

    net_adjustment_pct = parsed_total_adj / parsed_sale_price
    gross_adjustment_pct = gross_adjustment / parsed_sale_price
    dominant_share = (dominant_amount / gross_adjustment) if gross_adjustment > 0 else None

    size_gap_pct: Optional[float] = None
    sub_area = _safe_float(subject_living_area)
    cmp_area = _safe_float(comp_living_area)
    if sub_area is not None and cmp_area is not None and sub_area > 0:
        size_gap_pct = (sub_area - cmp_area) / sub_area

    flags = []
    if abs(net_adjustment_pct) >= flag_net_threshold:
        flags.append("high_net_adjustment_pct")
    if gross_adjustment_pct >= flag_gross_threshold:
        flags.append("high_gross_adjustment_pct")
    if size_gap_pct is not None and abs(size_gap_pct) >= flag_size_gap_threshold:
        flags.append("large_size_gap")
    if dominant_share is not None and dominant_share >= flag_dominant_share_threshold and dominant_factor:
        flags.append(f"dominant_{dominant_factor}_adjustment")

    group_reasons = []
    if abs(net_adjustment_pct) > primary_net_max:
        group_reasons.append("net_adjustment_above_primary_threshold")
    if gross_adjustment_pct > primary_gross_max:
        group_reasons.append("gross_adjustment_above_primary_threshold")
    if "large_size_gap" in flags:
        group_reasons.append("large_size_gap")
    group = "support" if group_reasons else "primary"

    penalty_points = 0
    for flag in flags:
        penalty_points += int(PENALTY_BY_FLAG.get(flag, 0))
    penalty_points = min(penalty_points, MAX_PENALTY_POINTS)

    return {
        "group": group,
        "group_reasons": group_reasons,
        "flags": sorted(set(flags)),
        "penalty_points": penalty_points,
        "net_adjustment_pct": round(net_adjustment_pct, 6),
        "gross_adjustment_pct": round(gross_adjustment_pct, 6),
        "dominant_factor": dominant_factor,
        "dominant_share": round(dominant_share, 4) if dominant_share is not None else None,
        "size_gap_pct": round(size_gap_pct, 6) if size_gap_pct is not None else None,
    }
