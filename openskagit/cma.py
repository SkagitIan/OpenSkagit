from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from django.contrib.gis.measure import D

from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db.models.expressions import RawSQL
from django.db.models import F, OuterRef, Subquery, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from .models import Assessor, Sales
from .improvement_utils import rollup_for_parcel


DEFAULT_COMPARABLE_LIMIT = 16
MAX_COMPARABLE_LIMIT = 24

from openskagit.models import RegressionAdjustment


logger = logging.getLogger(__name__)

FIELD_MAP: Dict[str, str] = {
    "bath_sq": "bathrooms",
    "bathrooms": "bathrooms",
    "bedrooms": "bedrooms",
    "effective_age": "effective_age",
    "has_attached_garage": "has_attached_garage",
    "has_detached_garage": "has_detached_garage",
    # log variables use dedicated handling but map to canonical field names for labels
    "log_area": "living_area",
    "log_lot": "acres",
}

RollupCache = Dict[Tuple[str, Optional[int], Optional[int]], Dict[str, object]]


def get_improvement_rollup(
    parcel_number: str,
    *,
    roll_year: Optional[int] = None,
    roll_id: Optional[int] = None,
    assessor_building_style: Optional[str] = None,
    cache: Optional[RollupCache] = None,
) -> Dict[str, object]:
    """
    Fetch an improvement rollup, memoizing via the provided cache when available.
    """
    key = (parcel_number, roll_id, roll_year)
    if cache is not None and key in cache:
        return cache[key]

    try:
        rollup = rollup_for_parcel(
            parcel_number,
            roll_year=roll_year,
            roll_id=roll_id,
            assessor_building_style=assessor_building_style,
        )
    except Exception:
        rollup = {}

    if cache is not None:
        cache[key] = rollup
    return rollup

def load_regression_adjustments():
    """Load regression-derived percentage adjustments from the database."""
    qs = RegressionAdjustment.objects.order_by("-created_at")
    adjustments = {r.variable: Decimal(str(r.adjustment_pct)) for r in qs}
    return adjustments


@dataclass(frozen=True)
class AdjustmentRule:
    key: str
    label: str
    attribute: str
    rate: Decimal
    rationale: str
    threshold: Decimal = Decimal("0")
    is_percentage: bool = False



DIFFERENCE_ALERTS: Dict[str, Decimal] = {
    "living_area": Decimal("150"),
    "bedrooms": Decimal("1"),
    "bathrooms": Decimal("1"),
    "garage_sqft": Decimal("50"),
    "acres": Decimal("0.1"),
    "year_built": Decimal("10"),
}


@dataclass
class CmaFilters:
    sale_date_min: Optional[dt.date] = None
    sale_date_max: Optional[dt.date] = None
    property_type: Optional[str] = None
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    bbox: Optional[Polygon] = None

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "sale_date_min": self.sale_date_min.isoformat() if self.sale_date_min else None,
            "sale_date_max": self.sale_date_max.isoformat() if self.sale_date_max else None,
            "property_type": self.property_type,
            "min_price": str(self.min_price) if self.min_price is not None else None,
            "max_price": str(self.max_price) if self.max_price is not None else None,
            "bedrooms": str(self.bedrooms) if self.bedrooms is not None else None,
            "bathrooms": str(self.bathrooms) if self.bathrooms is not None else None,
            "bbox": ",".join(str(x) for x in self.bbox.extent) if self.bbox else None,
        }


@dataclass
class AdjustmentLine:
    code: str
    label: str
    amount: Decimal
    rationale: str


@dataclass
class PropertySnapshot:
    parcel_number: str
    address: str
    sale_price: Optional[Decimal]
    sale_date: Optional[dt.date]
    property_type: Optional[str]
    living_area: Optional[Decimal]
    bedrooms: Optional[Decimal]
    bathrooms: Optional[Decimal]
    year_built: Optional[int]
    effective_year_built: Optional[int]
    garage_sqft: Optional[Decimal]
    acres: Optional[Decimal]
    geom: Optional[GEOSGeometry]
    metadata: Dict[str, Optional[str]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "parcel_number": self.parcel_number,
            "address": self.address,
            "sale_price": str(self.sale_price) if self.sale_price is not None else None,
            "sale_date": self.sale_date.isoformat() if self.sale_date else None,
            "property_type": self.property_type,
            "living_area": float(self.living_area) if self.living_area is not None else None,
            "bedrooms": float(self.bedrooms) if self.bedrooms is not None else None,
            "bathrooms": float(self.bathrooms) if self.bathrooms is not None else None,
            "year_built": self.year_built,
            "effective_year_built": self.effective_year_built,
            "garage_sqft": float(self.garage_sqft) if self.garage_sqft is not None else None,
            "acres": float(self.acres) if self.acres is not None else None,
            "metadata": self.metadata,
        }


@dataclass
class ComparableResult:
    snapshot: PropertySnapshot
    sale_price: Decimal
    sale_date: Optional[dt.date]
    distance_meters: Optional[float]
    distance_miles: Optional[Decimal]
    auto_adjustments: List[AdjustmentLine]
    manual_adjustments: Dict[str, Decimal]
    adjusted_price: Decimal
    gross_adjustment_total: Decimal
    gross_percentage_adjustment: Decimal
    difference_flags: Dict[str, bool]
    inclusion_rank: int

    def marker_payload(self) -> Dict[str, object]:
        geom = self.snapshot.geom
        if not geom:
            return {}
        return {
            "parcel_number": self.snapshot.parcel_number,
            "lat": geom.y,
            "lon": geom.x,
            "sale_price": float(self.sale_price),
            "adjusted_price": float(self.adjusted_price),
            "gpa": float(self.gross_percentage_adjustment),
            "address": self.snapshot.address,
            "rank": self.inclusion_rank,
        }


@dataclass
class CmaComputation:
    subject: PropertySnapshot
    comparables: List[ComparableResult]
    filters: CmaFilters
    sort_field: str
    sort_direction: str

    def summary(self) -> Dict[str, object]:
        adjusted_values = [comp.adjusted_price for comp in self.comparables]
        if not adjusted_values:
            return {
                "count": 0,
                "average": None,
                "median": None,
                "low": None,
                "high": None,
            }

        quantized = [value.quantize(Decimal("0.01")) for value in adjusted_values]
        average = sum(quantized) / Decimal(len(quantized))
        sorted_values = sorted(quantized)
        if len(sorted_values) % 2 == 1:
            median = sorted_values[len(sorted_values) // 2]
        else:
            median = (sorted_values[len(sorted_values) // 2 - 1] + sorted_values[len(sorted_values) // 2]) / Decimal(
                "2.0"
            )
        return {
            "count": len(quantized),
            "average": average.quantize(Decimal("0.01")),
            "median": median.quantize(Decimal("0.01")),
            "low": min(quantized),
            "high": max(quantized),
        }

    def marker_payloads(self) -> List[Dict[str, object]]:
        markers: List[Dict[str, object]] = []
        subject_geom = self.subject.geom
        if subject_geom:
            markers.append(
                {
                    "type": "subject",
                    "parcel_number": self.subject.parcel_number,
                    "lat": subject_geom.y,
                    "lon": subject_geom.x,
                    "address": self.subject.address,
                }
            )
        for comp in self.comparables:
            payload = comp.marker_payload()
            if payload:
                payload["type"] = "comparable"
                markers.append(payload)
        return markers


def _to_decimal(value: Optional[object]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return None


def _safe_date(value: Optional[dt.datetime]) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def load_subject(
    parcel_number: str,
    *,
    roll_year: Optional[int] = None,
    rollup_cache: Optional[RollupCache] = None,
) -> PropertySnapshot:
    """
    Load a parcel snapshot for CMA workflows.

    When multiple AssessmentRoll years exist, prefer the explicitly requested year,
    or fall back to the most recent year available.
    """
    qs = Assessor.objects.filter(parcel_number=parcel_number)
    if roll_year is not None:
        qs = qs.filter(roll__year=roll_year)
    else:
        qs = qs.order_by("-roll__year", "-id")

    assessor = qs.select_related("roll").first()
    if assessor is None:
        raise ValueError(f"Parcel {parcel_number} could not be located")

    if assessor.geom is None:
        raise ValueError("Subject property does not have geospatial coordinates.")

    # Prefer SALES table for last sale details; handle multiple rows safely
    sale_row = (
        Sales.objects.filter(
            parcel_number=assessor.parcel_number,
            sale_type__iregex=r"^\s*valid sale\s*$",
        )
        .order_by("-sale_date")
        .first()
    )

    subject_roll_year = assessor.roll.year if getattr(assessor, "roll", None) else None
    subject_roll_id = assessor.roll_id if getattr(assessor, "roll_id", None) else None

    snapshot = PropertySnapshot(
        parcel_number=assessor.parcel_number,
        address=assessor.address or "Unknown address",
        sale_price=_to_decimal(sale_row.sale_price if sale_row else assessor.sale_price),
        sale_date=_safe_date(sale_row.sale_date if sale_row else assessor.sale_date),
        property_type=assessor.property_type,
        living_area=_to_decimal(assessor.living_area),
        bedrooms=_to_decimal(assessor.bedrooms),
        bathrooms=_to_decimal(assessor.bathrooms),
        year_built=int(assessor.year_built) if assessor.year_built else None,
        effective_year_built=int(assessor.eff_year_built) if assessor.eff_year_built else None,
        garage_sqft=_to_decimal(assessor.garage_sqft),
        acres=_to_decimal(assessor.acres),
        geom=assessor.geom,
        metadata={
            "neighborhood_code": assessor.neighborhood_code,
            "land_use_code": assessor.land_use_code,
            "assessment_roll_year": subject_roll_year,
            "roll_year": subject_roll_year,
            "roll_id": subject_roll_id,
            "assessor_building_style": assessor.building_style,
        },
    )

    # Attach improvement rollup for subject display and downstream pages
    snapshot.metadata["improvements"] = get_improvement_rollup(
        assessor.parcel_number,
        roll_year=subject_roll_year,
        roll_id=subject_roll_id,
        assessor_building_style=assessor.building_style,
        cache=rollup_cache,
    )

    return snapshot


def _base_queryset(subject: PropertySnapshot) -> Iterable[Assessor]:
    # Annotate assessor parcels with sales facts from SALES; use SALES for comps
    sale_sq_base = Sales.objects.filter(
        parcel_number=OuterRef("parcel_number"),
        sale_type__iregex=r"^\s*valid sale\s*$",
    ).order_by("-sale_date")

    sale_sq_price = Subquery(sale_sq_base.values("sale_price")[:1])
    sale_sq_date = Subquery(sale_sq_base.values("sale_date")[:1])
    sale_sq_deed = Subquery(sale_sq_base.values("deed_type")[:1])

    qs = (
        Assessor.objects.filter(geom__isnull=False)
        .only(
            "parcel_number",
            "address",
            "living_area",
            "bedrooms",
            "bathrooms",
            "garage_sqft",
            "acres",
            "year_built",
            "eff_year_built",
            "geom",
            "property_type",
            "neighborhood_code",
            "building_style",
        )
        .exclude(parcel_number=subject.parcel_number)
        .filter(geom__distance_lte=(subject.geom, D(m=8000)))  # <— add this line
        .annotate(
            comp_sale_price=sale_sq_price,
            comp_sale_date=sale_sq_date,
            comp_deed_type=sale_sq_deed,
        )
        .filter(comp_sale_price__gt=0)
        .annotate(
            parcel_rank=Window(
                expression=RowNumber(),
                partition_by=[F("parcel_number")],
                order_by=[
                    F("roll__year").desc(nulls_last=True),
                    F("id").desc(),
                ],
            )
        )
        .filter(parcel_rank=1)
        .annotate(
            distance_sort=RawSQL("geom <-> %s", (subject.geom.ewkb,) if subject.geom else (None,)),
            # Use ST_Distance on geography to avoid missing function errors
            distance_meters=RawSQL(
                "CASE WHEN geom IS NULL OR %s IS NULL THEN NULL "
                "ELSE ST_Distance(geom::geography, %s::geography) END",
                (subject.geom.ewkb, subject.geom.ewkb) if subject.geom else (None, None),
            ),
        )
        .select_related()
    )
    return qs


def apply_filters(qs: Iterable[Assessor], filters: CmaFilters) -> Iterable[Assessor]:
    if filters.property_type:
        qs = qs.filter(property_type__iexact=filters.property_type)
    if filters.sale_date_min:
        start_dt = dt.datetime.combine(filters.sale_date_min, dt.time.min)
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt)
        qs = qs.filter(comp_sale_date__gte=start_dt)
    if filters.sale_date_max:
        end_dt = dt.datetime.combine(filters.sale_date_max, dt.time.max)
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt)
        qs = qs.filter(comp_sale_date__lte=end_dt)
    if filters.min_price is not None:
        qs = qs.filter(comp_sale_price__gte=filters.min_price)
    if filters.max_price is not None:
        qs = qs.filter(comp_sale_price__lte=filters.max_price)
    if filters.bedrooms is not None:
        qs = qs.filter(bedrooms__gte=filters.bedrooms)
    if filters.bathrooms is not None:
        qs = qs.filter(bathrooms__gte=filters.bathrooms)
    if filters.bbox:
        qs = qs.filter(geom__within=filters.bbox)
    return qs

from decimal import Decimal, ROUND_HALF_UP

def _safe_decimal(val):
    """Convert to Decimal safely, returning None on bad input."""
    try:
        return Decimal(str(val))
    except Exception:
        return None

def _log_ratio_delta(subj_val, comp_val):
    """Return the log ratio delta between subject and comp (safe)."""
    try:
        s, c = float(subj_val), float(comp_val)
        if s > 0 and c > 0:
            return Decimal(np.log(s / c))
    except Exception:
        pass
    return Decimal(0)

def _get_code(obj, field_prefix):
    """Try to pull code from .metadata or direct field."""
    if hasattr(obj, "metadata") and isinstance(obj.metadata, dict):
        return obj.metadata.get(field_prefix)
    return getattr(obj, field_prefix, None)


def _numeric_feature(obj: object, field: str):
    """
    Resolve numeric attributes used for adjustments.

    Handles derived fields such as `effective_age` that may not exist on the
    underlying object, falling back to raw attributes when present.
    """
    if field == "effective_age":
        year_built = getattr(obj, "year_built", None)
        eff_year_built = getattr(obj, "effective_year_built", None)
        if eff_year_built is None:
            eff_year_built = getattr(obj, "eff_year_built", None)
        if year_built is not None and eff_year_built is not None:
            try:
                delta = Decimal(str(year_built)) - Decimal(str(eff_year_built))
            except Exception:
                delta = None
            if isinstance(delta, Decimal) and delta < 0:
                delta = Decimal("0")
            if delta is not None:
                return delta
        return getattr(obj, field, None)
    return getattr(obj, field, None)
from decimal import Decimal, ROUND_HALF_UP
import numpy as np

def _compute_adjustments(subject, comp_record):
    """
    Compute regression-based auto adjustments between a subject and comp.

    Each RegressionAdjustment record provides a % effect per variable.
    This function compares the subject and comp for that variable and
    multiplies the delta by the % rate and comp sale price.
    """
    adj_factors = load_regression_adjustments()  # latest model version
    adjustments, difference_flags = [], {}
    base_value = Decimal(getattr(comp_record, "comp_sale_price", 0) or 1)

    if base_value <= 1:
        logger.warning("CMA adjustments skipped: missing sale price for parcel=%s", getattr(comp_record, "parcel_number", "?"))
        return [], {}

    for key, pct in adj_factors.items():
        try:
            pct = Decimal(str(pct))
        except Exception:
            continue
        # skip nulls, but keep small rates (can matter!)
        if pct is None:
            continue

        canonical_field = FIELD_MAP.get(key, key)
        field = None
        adj_amount = Decimal(0)
        delta = Decimal(0)

        # --- Continuous log-type ---
        if key in ["log_area", "log_lot"]:
            field = "living_area" if key == "log_area" else "acres"
            s = getattr(subject, field, 0) or 0
            c = getattr(comp_record, field, 0) or 0
            try:
                if s > 0 and c > 0:
                    delta = Decimal(np.log(s / c))
                    adj_amount = base_value * (pct / Decimal("100")) * delta
            except Exception:
                pass

        # --- Linear count features ---
        elif canonical_field in ["bedrooms", "bathrooms", "effective_age"]:
            field = canonical_field
            subj = _safe_decimal(_numeric_feature(subject, field))
            comp = _safe_decimal(_numeric_feature(comp_record, field))
            if subj is None or comp is None:
                continue
            delta = subj - comp
            adj_amount = base_value * (pct / Decimal("100")) * delta

        # --- Garage flags ---
        elif canonical_field in ["has_attached_garage", "has_detached_garage"]:
            field = canonical_field
            subj = int(bool(getattr(subject, field, 0)))
            comp = int(bool(getattr(comp_record, field, 0)))
            delta = Decimal(subj - comp)
            adj_amount = base_value * (pct / Decimal("100")) * delta

        # --- Condition / Land Use / Neighborhood codes ---
        elif any(prefix in key for prefix in ["condition_code_", "land_use_code_", "neighborhood_code_"]):
            parts = canonical_field.split("_")
            field_prefix = "_".join(parts[:2])  # e.g., "condition_code"
            field = field_prefix

            subj_code = _get_code(subject, field_prefix)
            comp_code = _get_code(comp_record, field_prefix)
            dummy_suffix = key.split(field_prefix + "_")[-1]

            if (
                str(comp_code).strip().upper() == str(dummy_suffix).strip().upper()
                and subj_code != comp_code
            ):
                delta = Decimal(1)
                adj_amount = base_value * (pct / Decimal("100")) * delta

        # --- Skip unrecognized keys ---
        else:
            continue

        # --- finalize ---
        if field is None or adj_amount == 0:
            continue

        adj_amount = adj_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rationale = f"{pct:+.2f}% effect on {field} (Δ={delta})"
        adjustments.append(
            AdjustmentLine(
                code=key,
                label=field.replace("_", " ").title(),
                amount=adj_amount,
                rationale=rationale,
            )
        )
        difference_flags[field] = delta != 0

        # --- Debug log ---
        logger.debug(
            "CMA auto adjustment | parcel=%s field=%s delta=%s pct=%s amount=%s",
            getattr(comp_record, "parcel_number", "?"),
            field,
            delta,
            pct,
            adj_amount,
        )

    if not adjustments:
        logger.debug(
            "CMA auto adjustment | parcel=%s generated no adjustments | factors=%s",
            getattr(comp_record, "parcel_number", "?"),
            list(adj_factors.keys()),
        )

    return adjustments, difference_flags

def _manual_adjustment_total(manual_adjustments: Dict[str, Decimal]) -> Decimal:
    total = Decimal("0")
    for value in manual_adjustments.values():
        if value is None:
            continue
        total += Decimal(str(value))
    return total


def _gross_adjustment_total(auto_adjustments: Sequence[AdjustmentLine], manual_adjustments: Dict[str, Decimal]) -> Decimal:
    gross = Decimal("0")
    for adj in auto_adjustments:
        gross += abs(adj.amount)
    for value in manual_adjustments.values():
        gross += abs(Decimal(str(value)))
    return gross


def build_comparables(
    subject: PropertySnapshot,
    filters: CmaFilters,
    manual_adjustments: Dict[str, Dict[str, Decimal]],
    excluded: Sequence[str],
    sort_field: str,
    sort_direction: str,
    limit: int = DEFAULT_COMPARABLE_LIMIT,
    *,
    load_improvements: bool = True,
    rollup_cache: Optional[RollupCache] = None,
) -> CmaComputation:
    if limit > MAX_COMPARABLE_LIMIT:
        limit = MAX_COMPARABLE_LIMIT

    queryset = _base_queryset(subject)
    queryset = apply_filters(queryset, filters)
    queryset = queryset.order_by("distance_sort")[: max(limit, DEFAULT_COMPARABLE_LIMIT)]

    comparables: List[ComparableResult] = []

    for candidate in queryset:
        if candidate.parcel_number in excluded:
            continue
        sale_price = _to_decimal(getattr(candidate, "comp_sale_price", None))
        if sale_price is None or sale_price <= 0:
            continue
        auto_adjustments, difference_flags = _compute_adjustments(subject, candidate)
        auto_total = sum((adj.amount for adj in auto_adjustments), start=Decimal("0"))
        manual = manual_adjustments.get(candidate.parcel_number, {})
        manual_total = _manual_adjustment_total(manual)
        adjusted_price = (sale_price or Decimal("0")) + auto_total + manual_total
        gross_total = _gross_adjustment_total(auto_adjustments, manual)
        logger.debug(
            "CMA adjustments | parcel=%s sale=%s auto=%s manual=%s adjusted=%s manual_fields=%s",
            candidate.parcel_number,
            sale_price,
            auto_total,
            manual_total,
            adjusted_price,
            list(manual.keys()),
        )
        if auto_total == 0 and manual_total == 0:
            logger.debug(
                "CMA adjustments absent | parcel=%s | difference_flags=%s | subject_vals=%s | comp_vals=%s",
                candidate.parcel_number,
                difference_flags,
                {
                    "living_area": subject.living_area,
                    "bedrooms": subject.bedrooms,
                    "bathrooms": subject.bathrooms,
                    "acres": subject.acres,
                    "effective_year_built": subject.effective_year_built,
                    "year_built": subject.year_built,
                    "garage_sqft": subject.garage_sqft,
                    "metadata": subject.metadata,
                },
                {
                    "living_area": _to_decimal(candidate.living_area),
                    "bedrooms": _to_decimal(candidate.bedrooms),
                    "bathrooms": _to_decimal(candidate.bathrooms),
                    "acres": _to_decimal(candidate.acres),
                    "effective_year_built": _to_decimal(candidate.eff_year_built),
                    "year_built": _to_decimal(candidate.year_built),
                    "garage_sqft": _to_decimal(candidate.garage_sqft),
                    "metadata": {
                        "neighborhood_code": candidate.neighborhood_code,
                        "land_use_code": getattr(candidate, "land_use_code", None),
                    },
                },
            )
        if sale_price > 0:
            gpa = (gross_total / sale_price * Decimal("100")).quantize(Decimal("0.01"))
        else:
            gpa = Decimal("0")

        distance_meters = getattr(candidate, "distance_meters", None)
        distance_miles: Optional[Decimal] = None
        if distance_meters:
            distance_miles = (Decimal(str(distance_meters)) / Decimal("1609.344")).quantize(Decimal("0.01"))

        candidate_roll_year = candidate.roll.year if getattr(candidate, "roll", None) else None
        candidate_roll_id = candidate.roll_id if getattr(candidate, "roll_id", None) else None
        candidate_style = getattr(candidate, "building_style", None)

        comp_snapshot = PropertySnapshot(
            parcel_number=candidate.parcel_number,
            address=candidate.address or "Unknown address",
            sale_price=sale_price,
            sale_date=_safe_date(getattr(candidate, "comp_sale_date", None)),
            property_type=candidate.property_type,
            living_area=_to_decimal(candidate.living_area),
            bedrooms=_to_decimal(candidate.bedrooms),
            bathrooms=_to_decimal(candidate.bathrooms),
            year_built=int(candidate.year_built) if candidate.year_built else None,
            effective_year_built=int(candidate.eff_year_built) if candidate.eff_year_built else None,
            garage_sqft=_to_decimal(candidate.garage_sqft),
            acres=_to_decimal(candidate.acres),
            geom=candidate.geom,
            metadata={
                "sale_deed_type": getattr(candidate, "comp_deed_type", None),
                "neighborhood_code": candidate.neighborhood_code,
                "roll_year": candidate_roll_year,
                "roll_id": candidate_roll_id,
                "assessor_building_style": candidate_style,
            },
        )

        # Attach improvement rollup for comparable display
        if load_improvements:
            comp_snapshot.metadata["improvements"] = get_improvement_rollup(
                candidate.parcel_number,
                roll_year=candidate_roll_year,
                roll_id=candidate_roll_id,
                assessor_building_style=candidate_style,
                cache=rollup_cache,
            )
        else:
            comp_snapshot.metadata["improvements"] = {}

        comparables.append(
            ComparableResult(
                snapshot=comp_snapshot,
                sale_price=sale_price.quantize(Decimal("0.01")),
                sale_date=_safe_date(getattr(candidate, "comp_sale_date", None)),
                distance_meters=float(distance_meters) if distance_meters else None,
                distance_miles=distance_miles,
                auto_adjustments=auto_adjustments,
                manual_adjustments=manual,
                adjusted_price=adjusted_price,
                gross_adjustment_total=gross_total.quantize(Decimal("0.01")),
                gross_percentage_adjustment=gpa,
                difference_flags=difference_flags,
                inclusion_rank=0,
            )
        )

    comparables = _sort_comparables(comparables, sort_field, sort_direction)

    for idx, comp in enumerate(comparables, start=1):
        comp.inclusion_rank = idx

    return CmaComputation(
        subject=subject,
        comparables=comparables[:limit],
        filters=filters,
        sort_field=sort_field,
        sort_direction=sort_direction,
    )


def _sort_comparables(
    comparables: List[ComparableResult], sort_field: str, sort_direction: str
) -> List[ComparableResult]:
    reverse = sort_direction.lower() == "desc"

    key_map = {
        "sale_price": lambda c: c.sale_price,
        "adjusted_price": lambda c: c.adjusted_price,
        "distance": lambda c: c.distance_miles if c.distance_miles is not None else Decimal("0"),
        "sale_date": lambda c: c.sale_date or dt.date.min,
        "gpa": lambda c: c.gross_percentage_adjustment,
        "total_adjustment": lambda c: c.gross_adjustment_total,
    }
    key_func = key_map.get(sort_field, key_map["gpa"])
    return sorted(comparables, key=key_func, reverse=reverse)


def parse_filters_from_request(params: Dict[str, str]) -> CmaFilters:
    sale_date_min = _parse_date(params.get("sale_date_min"))
    sale_date_max = _parse_date(params.get("sale_date_max"))

    property_type = params.get("property_type") or None
    min_price = _parse_decimal(params.get("min_price"))
    max_price = _parse_decimal(params.get("max_price"))
    bedrooms = _parse_int(params.get("bedrooms"))
    bathrooms = _parse_int(params.get("bathrooms"))
    bbox = _parse_bbox(params.get("bbox"))

    return CmaFilters(
        sale_date_min=sale_date_min,
        sale_date_max=sale_date_max,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        bbox=bbox,
    )


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_bbox(value: Optional[str]) -> Optional[Polygon]:
    if not value:
        return None
    try:
        coords = [float(coord) for coord in value.split(",")]
        if len(coords) != 4:
            return None
        return Polygon.from_bbox(coords)
    except (TypeError, ValueError):
        return None


def fetch_sales_within_view(
    subject: PropertySnapshot,
    filters: CmaFilters,
    limit: int = 60,
) -> List[Dict[str, object]]:
    if not subject.geom or not filters.bbox:
        return []

    queryset = _base_queryset(subject)
    queryset = apply_filters(queryset, filters)
    queryset = queryset.order_by("distance_sort")[:limit]

    markers: List[Dict[str, object]] = []
    for candidate in queryset:
        if not candidate.geom:
            continue
        markers.append(
            {
                "parcel_number": candidate.parcel_number,
                "lat": candidate.geom.y,
                "lon": candidate.geom.x,
                "sale_price": float(getattr(candidate, "comp_sale_price", 0)) if getattr(candidate, "comp_sale_price", None) else None,
                "sale_date": _safe_date(getattr(candidate, "comp_sale_date", None)).isoformat()
                if _safe_date(getattr(candidate, "comp_sale_date", None))
                else None,
                "address": candidate.address,
            }
        )
    return markers


def filters_from_dict(payload: Dict[str, Any]) -> CmaFilters:
    if not isinstance(payload, dict):
        payload = {}
    return CmaFilters(
        sale_date_min=_parse_date(payload.get("sale_date_min")),
        sale_date_max=_parse_date(payload.get("sale_date_max")),
        property_type=payload.get("property_type"),
        min_price=_parse_decimal(payload.get("min_price")),
        max_price=_parse_decimal(payload.get("max_price")),
        bedrooms=_parse_int(payload.get("bedrooms")),
        bathrooms=_parse_int(payload.get("bathrooms")),
        bbox=_parse_bbox(payload.get("bbox")),
    )
