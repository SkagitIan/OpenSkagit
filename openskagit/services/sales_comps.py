from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openskagit import cma


DEFAULT_COMP_LIMIT = 12
MAX_COMP_LIMIT = 25
DEFAULT_BASE_RADIUS_M = 2500.0
DEFAULT_MAX_RADIUS_M = 12000.0
DEFAULT_LOOKBACK_MONTHS = 18
SFR_LAND_USE_CODES = {"110", "111", "112"}

IAAO_LEVEL_LOW = Decimal("0.90")
IAAO_LEVEL_HIGH = Decimal("1.10")
IAAO_PRD_LOW = Decimal("0.98")
IAAO_PRD_HIGH = Decimal("1.03")
IAAO_MIN_SAMPLE_SIZE = 5


@dataclass(frozen=True)
class SfrEligibilityTier:
    gla_min_ratio: float
    gla_max_ratio: float
    max_year_delta: int
    max_bath_delta: float
    max_bed_delta: float
    max_lot_bucket_delta: int
    allow_missing_bed_bath: bool
    max_quality_delta: float
    max_condition_delta: float


SFR_V1_TIERS: Tuple[SfrEligibilityTier, ...] = (
    SfrEligibilityTier(
        gla_min_ratio=0.75,
        gla_max_ratio=1.35,
        max_year_delta=20,
        max_bath_delta=1.0,
        max_bed_delta=2.0,
        max_lot_bucket_delta=0,
        allow_missing_bed_bath=False,
        max_quality_delta=2.0,
        max_condition_delta=2.0,
    ),
    SfrEligibilityTier(
        gla_min_ratio=0.70,
        gla_max_ratio=1.60,
        max_year_delta=30,
        max_bath_delta=1.5,
        max_bed_delta=3.0,
        max_lot_bucket_delta=1,
        allow_missing_bed_bath=True,
        max_quality_delta=2.5,
        max_condition_delta=2.5,
    ),
    SfrEligibilityTier(
        gla_min_ratio=0.60,
        gla_max_ratio=2.00,
        max_year_delta=45,
        max_bath_delta=2.0,
        max_bed_delta=4.0,
        max_lot_bucket_delta=2,
        allow_missing_bed_bath=True,
        max_quality_delta=3.0,
        max_condition_delta=3.0,
    ),
    SfrEligibilityTier(
        gla_min_ratio=0.50,
        gla_max_ratio=2.40,
        max_year_delta=60,
        max_bath_delta=2.5,
        max_bed_delta=5.0,
        max_lot_bucket_delta=3,
        allow_missing_bed_bath=True,
        max_quality_delta=4.0,
        max_condition_delta=4.0,
    ),
)


@dataclass
class SalesCompResult:
    subject: cma.PropertySnapshot
    comparables: List[cma.ComparableResult]
    radius_meters_used: float
    filters_applied: Dict[str, Any]
    iaao_metrics: Dict[str, Any]
    iaao_compliance: Dict[str, Any]
    warnings: List[str]


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _months_to_days(months: int) -> int:
    return max(1, int(round(float(months) * 30.4375)))


def _subject_metadata(subject: cma.PropertySnapshot) -> Dict[str, Any]:
    metadata = getattr(subject, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _cod_target_range(subject: cma.PropertySnapshot) -> Tuple[Decimal, Decimal]:
    prop = (subject.property_type or "").strip().upper()
    if prop == "R":
        return Decimal("5"), Decimal("15")
    return Decimal("5"), Decimal("20")


def _mean_confidence_interval(values: Sequence[float]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    n = len(values)
    if n < 2:
        return None, None
    stdev = statistics.stdev(values)
    margin = 1.96 * (stdev / math.sqrt(n))
    mean = statistics.fmean(values)
    return Decimal(str(mean - margin)), Decimal(str(mean + margin))


def _compute_prb(log_prices: Sequence[float], ratios: Sequence[float]) -> Optional[Decimal]:
    if len(log_prices) != len(ratios) or len(log_prices) < 3:
        return None
    x_mean = statistics.fmean(log_prices)
    y_mean = statistics.fmean(ratios)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(log_prices, ratios))
    denominator = sum((x - x_mean) ** 2 for x in log_prices)
    if denominator <= 0:
        return None
    return Decimal(str(numerator / denominator))


def _compute_iaao_metrics(
    subject: cma.PropertySnapshot,
    comparables: Sequence[cma.ComparableResult],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    ratios: List[float] = []
    sales: List[float] = []
    assessed_values: List[float] = []
    log_prices: List[float] = []
    warnings: List[str] = []

    for comp in comparables:
        sale_price = _safe_float(getattr(comp, "sale_price", None))
        assessed = _safe_float(getattr(comp, "assessed_value", None))
        if sale_price is None or assessed is None or sale_price <= 0 or assessed <= 0:
            continue
        ratio = assessed / sale_price
        ratios.append(ratio)
        sales.append(sale_price)
        assessed_values.append(assessed)
        try:
            log_prices.append(math.log(sale_price))
        except (TypeError, ValueError):
            pass

    sample_size = len(ratios)
    median_ratio: Optional[Decimal] = None
    mean_ratio: Optional[Decimal] = None
    weighted_mean_ratio: Optional[Decimal] = None
    cod: Optional[Decimal] = None
    prd: Optional[Decimal] = None
    prb: Optional[Decimal] = None
    mean_ci_lower: Optional[Decimal] = None
    mean_ci_upper: Optional[Decimal] = None

    if sample_size > 0:
        median_float = statistics.median(ratios)
        mean_float = statistics.fmean(ratios)
        weighted_float = sum(assessed_values) / sum(sales) if sum(sales) > 0 else None

        median_ratio = Decimal(str(median_float))
        mean_ratio = Decimal(str(mean_float))
        weighted_mean_ratio = Decimal(str(weighted_float)) if weighted_float is not None else None

        if median_float > 0:
            abs_deviation_median = statistics.median(abs(value - median_float) for value in ratios)
            cod = Decimal(str((abs_deviation_median / median_float) * 100.0))

        if weighted_float and weighted_float > 0:
            prd = Decimal(str(mean_float / weighted_float))

        prb = _compute_prb(log_prices, ratios)
        mean_ci_lower, mean_ci_upper = _mean_confidence_interval(ratios)

    cod_low, cod_high = _cod_target_range(subject)
    level_ok = (
        median_ratio is not None
        and IAAO_LEVEL_LOW <= median_ratio <= IAAO_LEVEL_HIGH
    )
    cod_ok = (
        cod is not None
        and cod_low <= cod <= cod_high
    )
    prd_ok = (
        prd is not None
        and IAAO_PRD_LOW <= prd <= IAAO_PRD_HIGH
    )
    sample_size_ok = sample_size >= IAAO_MIN_SAMPLE_SIZE
    sales_chasing_suspect = cod is not None and cod < Decimal("5") and sample_size >= 30

    if sample_size < IAAO_MIN_SAMPLE_SIZE:
        warnings.append("IAAO caution: fewer than 5 valid ratios in comp set.")
    if cod is not None and cod < Decimal("5"):
        warnings.append("COD below 5 can indicate over-smoothing or potential sales chasing.")
    if not level_ok and median_ratio is not None:
        warnings.append("Median level falls outside IAAO 0.90–1.10 target range.")
    if prd is not None and not prd_ok:
        warnings.append("PRD falls outside IAAO 0.98–1.03 target range.")

    iaao_metrics: Dict[str, Any] = {
        "sample_size": sample_size,
        "median_ratio": median_ratio,
        "mean_ratio": mean_ratio,
        "weighted_mean_ratio": weighted_mean_ratio,
        "cod": cod,
        "prd": prd,
        "prb": prb,
        "mean_ratio_ci_95_lower": mean_ci_lower,
        "mean_ratio_ci_95_upper": mean_ci_upper,
    }
    iaao_compliance: Dict[str, Any] = {
        "level_ok": level_ok,
        "cod_ok": cod_ok,
        "prd_ok": prd_ok,
        "sample_size_ok": sample_size_ok,
        "sales_chasing_suspect": sales_chasing_suspect,
        "targets": {
            "level_low": IAAO_LEVEL_LOW,
            "level_high": IAAO_LEVEL_HIGH,
            "cod_low": cod_low,
            "cod_high": cod_high,
            "prd_low": IAAO_PRD_LOW,
            "prd_high": IAAO_PRD_HIGH,
            "min_sample_size": IAAO_MIN_SAMPLE_SIZE,
        },
    }
    return iaao_metrics, iaao_compliance, warnings


def _normalize_limit(limit: Optional[int]) -> int:
    try:
        parsed = int(limit) if limit is not None else DEFAULT_COMP_LIMIT
    except (TypeError, ValueError):
        parsed = DEFAULT_COMP_LIMIT
    return max(1, min(MAX_COMP_LIMIT, parsed))


def _normalize_months(months: Optional[int]) -> int:
    try:
        parsed = int(months) if months is not None else DEFAULT_LOOKBACK_MONTHS
    except (TypeError, ValueError):
        parsed = DEFAULT_LOOKBACK_MONTHS
    return max(1, min(120, parsed))


def _normalize_radius(value: Optional[float], default: float) -> float:
    try:
        parsed = float(value) if value is not None else float(default)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(100.0, parsed)


def _unique_comparables(comparables: Sequence[cma.ComparableResult]) -> List[cma.ComparableResult]:
    deduped: List[cma.ComparableResult] = []
    seen: set[str] = set()
    for comp in comparables:
        snapshot = getattr(comp, "snapshot", None)
        parcel = getattr(snapshot, "parcel_number", None)
        if not parcel or parcel in seen:
            continue
        seen.add(parcel)
        deduped.append(comp)
    return deduped


def _normalized_text(value: Any) -> str:
    if value in (None, "", "null"):
        return ""
    return str(value).strip().lower()


def _land_use_code(snapshot: cma.PropertySnapshot) -> str:
    metadata = _subject_metadata(snapshot)
    return _normalized_text(metadata.get("land_use_code"))


def _property_type(snapshot: cma.PropertySnapshot) -> str:
    return _normalized_text(getattr(snapshot, "property_type", None))


def _numeric_value(*values: Any) -> Optional[float]:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _living_area(snapshot: cma.PropertySnapshot) -> Optional[float]:
    metadata = _subject_metadata(snapshot)
    return _numeric_value(
        getattr(snapshot, "living_area", None),
        metadata.get("calculated_square_footage"),
    )


def _effective_year(snapshot: cma.PropertySnapshot) -> Optional[int]:
    for value in (
        getattr(snapshot, "effective_year_built", None),
        getattr(snapshot, "year_built", None),
    ):
        try:
            if value is None:
                continue
            parsed = int(value)
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            continue
    return None


def _lot_bucket(snapshot: cma.PropertySnapshot) -> Optional[int]:
    metadata = _subject_metadata(snapshot)
    acres = _numeric_value(
        getattr(snapshot, "acres", None),
        getattr(snapshot, "lot_acres", None),
        metadata.get("lot_acres"),
    )
    if acres is None or acres <= 0:
        return None
    if acres < 0.25:
        return 0
    if acres < 1.0:
        return 1
    if acres < 5.0:
        return 2
    return 3


def _lot_bucket_match(subject_bucket: Optional[int], comp_bucket: Optional[int], *, max_delta: int) -> bool:
    if subject_bucket is None or comp_bucket is None:
        return False
    return abs(subject_bucket - comp_bucket) <= max(0, int(max_delta))


def _has_major_gap(subject_value: Any, comp_value: Any, *, max_delta: float) -> bool:
    subj = _safe_float(subject_value)
    comp = _safe_float(comp_value)
    if subj is None or comp is None:
        return False
    return abs(subj - comp) > max_delta


def _is_manufactured(snapshot: cma.PropertySnapshot) -> bool:
    metadata = _subject_metadata(snapshot)
    land_use_desc = _normalized_text(metadata.get("land_use_description"))
    style = _normalized_text(metadata.get("assessor_building_style"))
    haystack = f"{land_use_desc} {style}"
    tokens = ("manufact", "mobile", "mfd", "double wide", "single wide")
    return any(token in haystack for token in tokens)


def _is_highway_frontage(snapshot: cma.PropertySnapshot) -> bool:
    address = (getattr(snapshot, "address", None) or "").upper()
    markers = (" STATE ROUTE ", " SR ", " HIGHWAY ", " HWY ", " US-")
    padded = f" {address} "
    return any(marker in padded for marker in markers)


def _rank_comparables(comparables: Sequence[cma.ComparableResult]) -> List[cma.ComparableResult]:
    def key(comp: cma.ComparableResult) -> Tuple[float, int, float]:
        score_obj = getattr(comp, "score", None)
        total = _safe_float(getattr(score_obj, "total_score", None)) or 0.0
        sale_date = getattr(comp, "sale_date", None)
        sale_ord = sale_date.toordinal() if hasattr(sale_date, "toordinal") else 0
        distance = _safe_float(getattr(comp, "distance_miles", None))
        distance_key = distance if distance is not None else 9999.0
        return (total, sale_ord, -distance_key)

    return sorted(comparables, key=key, reverse=True)


def _passes_sfr_v1_tier(
    subject: cma.PropertySnapshot,
    comp: cma.ComparableResult,
    tier: SfrEligibilityTier,
) -> bool:
    passed, _ = _evaluate_sfr_v1_tier(subject, comp, tier)
    return passed


def _evaluate_sfr_v1_tier(
    subject: cma.PropertySnapshot,
    comp: cma.ComparableResult,
    tier: SfrEligibilityTier,
) -> Tuple[bool, str]:
    snapshot = getattr(comp, "snapshot", None)
    if snapshot is None:
        return False, "missing_snapshot"

    # Keep property class aligned: SFR subject should only compare against SFR land-use comps.
    comp_land_use = _land_use_code(snapshot)
    if comp_land_use not in SFR_LAND_USE_CODES:
        return False, "land_use_mismatch"

    subject_prop_type = _property_type(subject)
    comp_prop_type = _property_type(snapshot)
    if subject_prop_type and comp_prop_type and subject_prop_type != comp_prop_type:
        return False, "property_type_mismatch"

    subject_gla = _living_area(subject)
    comp_gla = _living_area(snapshot)
    if subject_gla is None or comp_gla is None or subject_gla <= 0 or comp_gla <= 0:
        return False, "missing_living_area"
    gla_ratio = comp_gla / subject_gla
    if gla_ratio < tier.gla_min_ratio or gla_ratio > tier.gla_max_ratio:
        return False, "gla_ratio_out_of_range"

    subject_year = _effective_year(subject)
    comp_year = _effective_year(snapshot)
    if subject_year is None or comp_year is None:
        return False, "missing_year_built"
    if abs(subject_year - comp_year) > tier.max_year_delta:
        return False, "year_delta_too_large"

    subject_baths = _safe_float(getattr(subject, "bathrooms", None))
    comp_baths = _safe_float(getattr(snapshot, "bathrooms", None))
    if subject_baths is None or comp_baths is None:
        if tier.allow_missing_bed_bath:
            subject_baths = comp_baths = None
        else:
            return False, "missing_bathrooms"
    if subject_baths is not None and comp_baths is not None and abs(subject_baths - comp_baths) > tier.max_bath_delta:
        return False, "bath_delta_too_large"

    subject_beds = _safe_float(getattr(subject, "bedrooms", None))
    comp_beds = _safe_float(getattr(snapshot, "bedrooms", None))
    if subject_beds is None or comp_beds is None:
        if tier.allow_missing_bed_bath:
            subject_beds = comp_beds = None
        else:
            return False, "missing_bedrooms"
    if subject_beds is not None and comp_beds is not None and abs(subject_beds - comp_beds) > tier.max_bed_delta:
        return False, "bed_delta_too_large"

    subject_bucket = _lot_bucket(subject)
    comp_bucket = _lot_bucket(snapshot)
    if not _lot_bucket_match(
        subject_bucket,
        comp_bucket,
        max_delta=tier.max_lot_bucket_delta,
    ):
        return False, "lot_bucket_mismatch"

    if _is_manufactured(subject) != _is_manufactured(snapshot):
        return False, "manufactured_mismatch"
    if _is_highway_frontage(subject) != _is_highway_frontage(snapshot):
        return False, "highway_frontage_mismatch"

    subject_meta = _subject_metadata(subject)
    comp_meta = _subject_metadata(snapshot)
    if _has_major_gap(
        subject_meta.get("quality_score"),
        comp_meta.get("quality_score"),
        max_delta=tier.max_quality_delta,
    ):
        return False, "quality_mismatch"
    if _has_major_gap(
        subject_meta.get("condition_score"),
        comp_meta.get("condition_score"),
        max_delta=tier.max_condition_delta,
    ):
        return False, "condition_mismatch"

    return True, "eligible"


def _apply_selection_policy(
    subject: cma.PropertySnapshot,
    comparables: Sequence[cma.ComparableResult],
    *,
    limit: int,
) -> Tuple[List[cma.ComparableResult], str]:
    ranked = _rank_comparables(comparables)
    subject_land_use = _land_use_code(subject)
    if subject_land_use not in SFR_LAND_USE_CODES:
        return ranked[:limit], "default_v2"

    selected: List[cma.ComparableResult] = []
    for tier in SFR_V1_TIERS:
        tier_comps = [comp for comp in ranked if _passes_sfr_v1_tier(subject, comp, tier)]
        selected = _rank_comparables(tier_comps)
        if len(selected) >= limit:
            return selected[:limit], "sfr_v1"

    return selected[:limit], "sfr_v1"


def build_sales_comps_v2(
    subject: cma.PropertySnapshot,
    *,
    limit: Optional[int] = None,
    months: Optional[int] = None,
    base_radius_m: Optional[float] = None,
    max_radius_m: Optional[float] = None,
) -> SalesCompResult:
    """
    Canonical comparable-sales operation for UI + MCP.

    Inclusion standard:
    - Comp sales come from latest `sale_type == VALID SALE` records in `sales`.
    - VALID SALE is treated as the authoritative, manually validated arm's-length set.
    """

    normalized_limit = _normalize_limit(limit)
    normalized_months = _normalize_months(months)
    base_radius = _normalize_radius(base_radius_m, DEFAULT_BASE_RADIUS_M)
    max_radius = _normalize_radius(max_radius_m, DEFAULT_MAX_RADIUS_M)
    if max_radius < base_radius:
        max_radius = base_radius

    max_sale_age_days = _months_to_days(normalized_months)
    # Build a wider raw pool before policy gating so SFR eligibility evaluates
    # market candidates rather than a narrow pre-trim shortlist.
    request_limit = min(200, max(normalized_limit * 8, 80))

    first = cma.build_comparables(
        subject=subject,
        filters=None,
        excluded=[],
        sort_field="score",
        sort_direction="desc",
        limit=request_limit,
        radius_meters=base_radius,
        max_sale_age_days=max_sale_age_days,
        load_improvements=False,
        oversample_factor=2,
    )
    combined = list(first.comparables)
    radius_used = base_radius

    initial_candidates = _unique_comparables(combined)
    initial_selected, _ = _apply_selection_policy(
        subject,
        initial_candidates,
        limit=normalized_limit,
    )

    if len(initial_selected) < normalized_limit and max_radius > base_radius:
        second = cma.build_comparables(
            subject=subject,
            filters=None,
            excluded=[],
            sort_field="score",
            sort_direction="desc",
            limit=request_limit,
            radius_meters=max_radius,
            max_sale_age_days=max_sale_age_days,
            load_improvements=False,
            oversample_factor=2,
        )
        combined.extend(second.comparables)
        radius_used = max_radius

    deduped = _unique_comparables(combined)
    comparables, policy_version = _apply_selection_policy(
        subject,
        deduped,
        limit=normalized_limit,
    )
    iaao_metrics, iaao_compliance, warnings = _compute_iaao_metrics(subject, comparables)
    if policy_version == "sfr_v1" and len(comparables) < min(IAAO_MIN_SAMPLE_SIZE, normalized_limit):
        warnings.append(
            "SFR v1 eligibility produced fewer than 5 comps within configured radius/date limits."
        )

    metadata = _subject_metadata(subject)
    filters_applied = {
        "limit": normalized_limit,
        "months": normalized_months,
        "max_sale_age_days": max_sale_age_days,
        "base_radius_m": base_radius,
        "max_radius_m": max_radius,
        "radius_used_m": radius_used,
        "sale_type_rule": "VALID SALE",
        "manual_validation_assumption": True,
        "selection_policy": policy_version,
        "subject_parcel": subject.parcel_number,
        "subject_property_type": subject.property_type,
        "subject_land_use_code": metadata.get("land_use_code"),
        "subject_neighborhood_code": metadata.get("neighborhood_code"),
    }

    return SalesCompResult(
        subject=subject,
        comparables=comparables,
        radius_meters_used=radius_used,
        filters_applied=filters_applied,
        iaao_metrics=iaao_metrics,
        iaao_compliance=iaao_compliance,
        warnings=warnings,
    )


def diagnose_no_comp_path(
    subject: cma.PropertySnapshot,
    *,
    limit: Optional[int] = None,
    months: Optional[int] = None,
    base_radius_m: Optional[float] = None,
    max_radius_m: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Lightweight diagnostics for zero-comp cases so UI/system messages can explain
    why no sales survived retrieval + eligibility constraints.
    """
    from django.db.models import Count, Q

    normalized_limit = _normalize_limit(limit)
    normalized_months = _normalize_months(months)
    base_radius = _normalize_radius(base_radius_m, DEFAULT_BASE_RADIUS_M)
    max_radius = _normalize_radius(max_radius_m, DEFAULT_MAX_RADIUS_M)
    if max_radius < base_radius:
        max_radius = base_radius
    max_sale_age_days = _months_to_days(normalized_months)
    request_limit = min(200, max(normalized_limit * 8, 80))
    total_needed = request_limit * 2

    subject_meta = _subject_metadata(subject)
    subject_land_use = str(subject_meta.get("land_use_code") or "").strip()
    subject_property_type = (subject.property_type or "").strip()

    def _stage(radius_meters: float) -> Dict[str, Any]:
        qs_base = cma._base_queryset(
            subject,
            radius_meters=radius_meters,
            max_sale_age_days=max_sale_age_days,
        )

        qs_prop = qs_base
        if subject_property_type:
            qs_prop = qs_prop.filter(
                Q(proptype__iexact=subject_property_type)
                | Q(proptype__isnull=True)
                | Q(proptype__exact="")
            )
        else:
            qs_prop = qs_prop.filter(
                Q(proptype__iexact="R")
                | Q(proptype__isnull=True)
                | Q(proptype__exact="")
            )

        qs_year = qs_prop.filter(
            Q(final_year_built__isnull=False)
            | Q(year_built__isnull=False)
            | Q(eff_year_built__isnull=False)
            | Q(effective_yr_blt__isnull=False)
        )
        qs_area = qs_year.filter(
            Q(final_living_area__isnull=False)
            | Q(total_living_area__isnull=False)
            | Q(living_area__isnull=False)
        )

        qs_land_use = qs_area
        if subject_land_use:
            qs_land_use = qs_land_use.filter(
                Q(land_use_code__iexact=subject_land_use)
                | Q(land_use_code__isnull=True)
                | Q(land_use_code__exact="")
            )

        qs_distinct = qs_land_use.order_by("parcel_number").distinct("parcel_number")
        raw_rows = list(qs_distinct[:total_needed])

        dropped_missing_address = 0
        dropped_missing_address_parcels: List[str] = []
        for row in raw_rows:
            clean_address = cma._clean_address(getattr(row, "situs_address", None))
            if clean_address is None:
                dropped_missing_address += 1
                dropped_missing_address_parcels.append(str(getattr(row, "parcel_number", "")))

        top_land_use = list(
            qs_area.values("land_use_code")
            .annotate(count=Count("parcel_number"))
            .order_by("-count")[:8]
        )

        return {
            "radius_meters": float(radius_meters),
            "counts": {
                "base_queryset": qs_base.count(),
                "after_property_type_filter": qs_prop.count(),
                "after_year_presence_filter": qs_year.count(),
                "after_living_area_filter": qs_area.count(),
                "after_subject_land_use_filter": qs_land_use.count(),
                "after_distinct_parcel": qs_distinct.count(),
                "raw_rows_fetched": len(raw_rows),
                "dropped_missing_address": dropped_missing_address,
                "constructible_from_raw_rows": max(0, len(raw_rows) - dropped_missing_address),
            },
            "top_land_use_nearby": [
                {
                    "land_use_code": row.get("land_use_code"),
                    "count": int(row.get("count") or 0),
                }
                for row in top_land_use
            ],
            "dropped_missing_address_parcels": dropped_missing_address_parcels[:12],
        }

    base_stage = _stage(base_radius)
    max_stage = _stage(max_radius) if max_radius > base_radius else None
    active_stage = max_stage or base_stage
    active_counts = (active_stage or {}).get("counts") or {}

    reasons: List[str] = []
    if int(active_counts.get("base_queryset") or 0) <= 0:
        reasons.append(
            f"No VALID SALE records were found within {int(round((active_stage or {}).get('radius_meters') or 0))}m "
            f"and {normalized_months} months."
        )
    if subject_land_use and int(active_counts.get("after_subject_land_use_filter") or 0) <= 0:
        reasons.append(
            f"No nearby VALID SALE parcels matched subject land use code {subject_land_use}."
        )
    if (
        int(active_counts.get("raw_rows_fetched") or 0) > 0
        and int(active_counts.get("constructible_from_raw_rows") or 0) <= 0
        and int(active_counts.get("dropped_missing_address") or 0) > 0
    ):
        reasons.append(
            f"{int(active_counts.get('dropped_missing_address') or 0)} matching sale candidate(s) were excluded "
            "because situs address is missing in source records."
        )
    if (
        int(active_counts.get("base_queryset") or 0) > 0
        and int(active_counts.get("constructible_from_raw_rows") or 0) <= 0
        and not reasons
    ):
        reasons.append(
            "Candidates were found but none survived required data-quality checks for comparable construction."
        )

    nearby_codes = [
        str(row.get("land_use_code") or "").strip()
        for row in (active_stage or {}).get("top_land_use_nearby") or []
        if str(row.get("land_use_code") or "").strip()
    ]
    if nearby_codes:
        reasons.append(
            "Nearby VALID SALE activity is concentrated in land use code(s): "
            + ", ".join(nearby_codes[:5])
            + "."
        )

    reasons.append(
        "This parcel likely needs hand-worked comparable selection by appraisal staff."
    )

    return {
        "subject_land_use_code": subject_land_use or None,
        "months": normalized_months,
        "base_radius_m": base_radius,
        "max_radius_m": max_radius,
        "request_limit": request_limit,
        "base_stage": base_stage,
        "max_stage": max_stage,
        "active_stage": "max_radius" if max_stage else "base_radius",
        "reasons": reasons,
        "manual_review_recommended": True,
    }


def _serialize_decimal(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _comp_payload(
    comp: cma.ComparableResult,
    rank: int,
    *,
    subject_neighborhood: Optional[str],
    base_radius_m: float,
    max_radius_m: float,
) -> Dict[str, Any]:
    snapshot = comp.snapshot
    metadata = _subject_metadata(snapshot)
    point = snapshot.display_point()
    lat = point.y if point else snapshot.latitude
    lon = point.x if point else snapshot.longitude

    sale_price = _to_decimal(comp.sale_price)
    assessed_value = _to_decimal(comp.assessed_value)
    ratio = None
    if sale_price and assessed_value and sale_price > 0:
        ratio = assessed_value / sale_price

    distance_meters = _safe_float(comp.distance_meters)
    if distance_meters is None:
        distance_tier = None
    elif distance_meters <= base_radius_m:
        distance_tier = 0
    elif distance_meters <= max_radius_m:
        distance_tier = 1
    else:
        distance_tier = 2

    hood_code = metadata.get("neighborhood_code")
    hood_match = bool(subject_neighborhood and hood_code and hood_code == subject_neighborhood)

    score = comp.score
    similarity = {
        "total": _serialize_decimal(getattr(score, "total_score", None) if score else None),
        "location": _serialize_decimal(getattr(score, "location_score", None) if score else None),
        "time": _serialize_decimal(getattr(score, "time_score", None) if score else None),
        "physical": _serialize_decimal(getattr(score, "physical_score", None) if score else None),
    }

    return {
        "rn": rank,
        "parcel_number": snapshot.parcel_number,
        "sale_date": comp.sale_date.isoformat() if comp.sale_date else None,
        "sale_price": _serialize_decimal(sale_price),
        "assessed_value": _serialize_decimal(assessed_value),
        "sale_to_market_ratio": _serialize_decimal(ratio),
        "living_area": _serialize_decimal(_to_decimal(snapshot.living_area)),
        "lot_size_acres": _serialize_decimal(_to_decimal(snapshot.acres or snapshot.lot_acres)),
        "hood_code": hood_code,
        "land_use_code": metadata.get("land_use_code"),
        "situs_address": snapshot.address,
        "total_living_area": _serialize_decimal(_to_decimal(snapshot.living_area)),
        "total_baths": _serialize_decimal(_to_decimal(snapshot.bathrooms)),
        "year_built": snapshot.year_built,
        "effective_yr_blt": snapshot.effective_year_built,
        "final_living_area": _serialize_decimal(_to_decimal(snapshot.living_area)),
        "final_eff_yr_blt": snapshot.effective_year_built,
        "acres": _serialize_decimal(_to_decimal(snapshot.acres)),
        "quality_score": metadata.get("quality_score"),
        "condition_score": metadata.get("condition_score"),
        "distance_meters": distance_meters,
        "distance_miles": _serialize_decimal(_to_decimal(comp.distance_miles)),
        "hood_match": hood_match,
        "distance_tier": distance_tier,
        "lat": lat,
        "lon": lon,
        "similarity": similarity,
    }


def serialize_sales_comps_result(result: SalesCompResult) -> Dict[str, Any]:
    subject_meta = _subject_metadata(result.subject)
    base_radius = float(result.filters_applied.get("base_radius_m") or DEFAULT_BASE_RADIUS_M)
    max_radius = float(result.filters_applied.get("max_radius_m") or DEFAULT_MAX_RADIUS_M)
    subject_hood = subject_meta.get("neighborhood_code")

    comparables = [
        _comp_payload(
            comp,
            idx,
            subject_neighborhood=subject_hood,
            base_radius_m=base_radius,
            max_radius_m=max_radius,
        )
        for idx, comp in enumerate(result.comparables, start=1)
    ]

    return {
        "parcel_id": result.subject.parcel_number,
        "subject": {
            "parcel_number": result.subject.parcel_number,
            "land_use_code": subject_meta.get("land_use_code"),
            "hood_code": subject_hood,
            "situs_address": result.subject.address,
            "property_type": result.subject.property_type,
        },
        "filters": result.filters_applied,
        "iaao_metrics": {
            key: _serialize_decimal(value) if isinstance(value, Decimal) else value
            for key, value in result.iaao_metrics.items()
        },
        "iaao_compliance": {
            key: (
                {
                    nested_key: _serialize_decimal(nested_val) if isinstance(nested_val, Decimal) else nested_val
                    for nested_key, nested_val in value.items()
                }
                if isinstance(value, dict)
                else value
            )
            for key, value in result.iaao_compliance.items()
        },
        "warnings": result.warnings,
        "comparables": comparables,
    }
