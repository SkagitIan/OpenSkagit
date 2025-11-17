from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from django.contrib.gis.measure import D

from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db.models.expressions import RawSQL
from django.db.models import F, OuterRef, Subquery, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from .models import Assessor, Sales
from .improvement_utils import rollup_for_parcel
from .valuation_areas import resolve_market_group


DEFAULT_COMPARABLE_LIMIT = 16
MAX_COMPARABLE_LIMIT = 24

logger = logging.getLogger(__name__)

RollupCache = Dict[Tuple[str, Optional[int], Optional[int]], Dict[str, object]]

WGS84_SRID = 4326


def _ensure_wgs84(geom: Optional[GEOSGeometry]) -> Optional[GEOSGeometry]:
    if geom is None:
        return None
    if getattr(geom, "srid", None) == WGS84_SRID:
        return geom
    cloned = GEOSGeometry(geom.wkb, srid=geom.srid)
    cloned.transform(WGS84_SRID)
    return cloned


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
    assessed_value: Optional[Decimal]
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
            "assessed_value": float(self.assessed_value) if self.assessed_value is not None else None,
            "metadata": self.metadata,
        }


@dataclass
class ComparableResult:
    snapshot: PropertySnapshot
    sale_price: Decimal
    assessed_value: Optional[Decimal]
    sale_date: Optional[dt.date]
    distance_meters: Optional[float]
    distance_miles: Optional[Decimal]
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
            "assessed_value": float(self.assessed_value) if self.assessed_value is not None else None,
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
        sale_values = [comp.sale_price for comp in self.comparables]
        if not sale_values:
            return {
                "count": 0,
                "average": None,
                "median": None,
                "low": None,
                "high": None,
            }

        quantized = [value.quantize(Decimal("0.01")) for value in sale_values]
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

    subject_geom = _ensure_wgs84(assessor.geom)
    if subject_geom is None:
        raise ValueError("Unable to project subject geometry to WGS84.")

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

    subject_market_group = resolve_market_group(assessor.neighborhood_code) or assessor.city_district

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
        assessed_value=_to_decimal(assessor.assessed_value),
        geom=subject_geom,
        metadata={
            "neighborhood_code": assessor.neighborhood_code,
            "land_use_code": assessor.land_use_code,
            "city_district": assessor.city_district,
            "valuation_area": subject_market_group,
            "assessment_roll_year": subject_roll_year,
            "roll_year": subject_roll_year,
            "roll_id": subject_roll_id,
            "assessor_building_style": assessor.building_style,
            "assessed_value": float(assessor.assessed_value) if assessor.assessed_value is not None else None,
            "finished_basement_sqft": float(assessor.finished_basement) if assessor.finished_basement else None,
            "unfinished_basement_sqft": float(assessor.unfinished_basement) if assessor.unfinished_basement else None,
        },
    )
    has_basement = False
    if assessor.finished_basement and assessor.finished_basement > 0:
        has_basement = True
    if assessor.unfinished_basement and assessor.unfinished_basement > 0:
        has_basement = True
    snapshot.metadata["has_basement"] = has_basement

    # Attach improvement rollup for subject display and downstream pages
    snapshot.metadata["improvements"] = get_improvement_rollup(
        assessor.parcel_number,
        roll_year=subject_roll_year,
        roll_id=subject_roll_id,
        assessor_building_style=assessor.building_style,
        cache=rollup_cache,
    )

    return snapshot


def _base_queryset(subject: PropertySnapshot, radius_meters: Optional[float]) -> Iterable[Assessor]:
    # Subqueries for SALES table
    sale_sq_base = Sales.objects.filter(
        parcel_number=OuterRef("parcel_number"),
        sale_type__iregex=r"^\s*valid sale\s*$",
    ).order_by("-sale_date")

    sale_sq_price = Subquery(sale_sq_base.values("sale_price")[:1])
    sale_sq_date = Subquery(sale_sq_base.values("sale_date")[:1])
    sale_sq_deed = Subquery(sale_sq_base.values("deed_type")[:1])

    # Subject geography (point)
    subject_geom = subject.geom
    subject_geom_param = subject_geom.ewkb if subject_geom else None

    subject_point_geog = RawSQL(
        "%s::geography",
        (subject_geom_param,),
        output_field=gis_models.PointField(geography=True, srid=WGS84_SRID),
    )

    # -----------------------------------------------------
    # BASE QUERYSET – SPATIAL PRUNING FIRST (very fast)
    # -----------------------------------------------------
    qs = Assessor.objects.filter(geom__isnull=False, roll__year=2025, property_type='R')

    if radius_meters is not None and subject_geom_param:
        qs = qs.filter(
            centroid_geog__distance_lte=(
                subject_point_geog,
                radius_meters,
            )
        )

    # Only select fields needed later
    qs = qs.only(
        "parcel_number",
        "address",
        "living_area",
        "bedrooms",
        "bathrooms",
        "garage_sqft",
        "acres",
        "year_built",
        "eff_year_built",
        "finished_basement",
        "unfinished_basement",
        "geom",
        "property_type",
        "neighborhood_code",
        "building_style",
        "city_district",
        "assessed_value",
    )

    # Exclude subject parcel
    qs = qs.exclude(parcel_number=subject.parcel_number)

    # Attach sales subqueries
    qs = qs.annotate(
        comp_sale_price=sale_sq_price,
        comp_sale_date=sale_sq_date,
        comp_deed_type=sale_sq_deed,
    ).filter(comp_sale_price__gt=0)

    # Pick latest roll per parcel
    qs = qs.annotate(
        parcel_rank=Window(
            expression=RowNumber(),
            partition_by=[F("parcel_number")],
            order_by=[
                F("roll__year").desc(nulls_last=True),
                F("id").desc(),
            ],
        )
    ).filter(parcel_rank=1)

    # Distance annotations — uses centroid_geog (indexed)
    qs = qs.annotate(
        distance_sort=RawSQL(
            "centroid_geog <-> %s::geography",
            (subject_geom_param,)
        ),
        distance_meters=RawSQL(
            "ST_Distance(centroid_geog, %s::geography)",
            (subject_geom_param,)
        ),
    )

    # Enforce radius again (cheap now)
    if radius_meters is not None:
        qs = qs.filter(distance_meters__lte=radius_meters)

    return qs.select_related()

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

def build_comparables(
    subject: PropertySnapshot,
    filters: CmaFilters,
    excluded: Sequence[str],
    sort_field: str,
    sort_direction: str,
    limit: int = DEFAULT_COMPARABLE_LIMIT,
    *,
    radius_meters: Optional[float] = 8000,
    load_improvements: bool = True,
    rollup_cache: Optional[RollupCache] = None,
) -> CmaComputation:
    if limit > MAX_COMPARABLE_LIMIT:
        limit = MAX_COMPARABLE_LIMIT

    queryset = _base_queryset(subject, radius_meters)
    queryset = apply_filters(queryset, filters)
    queryset = queryset.order_by("distance_sort")[: max(limit, DEFAULT_COMPARABLE_LIMIT)]

    comparables: List[ComparableResult] = []

    for candidate in queryset:
        if candidate.parcel_number in excluded:
            continue
        sale_price = _to_decimal(getattr(candidate, "comp_sale_price", None))
        if sale_price is None or sale_price <= 0:
            continue
        difference_flags = _compute_difference_flags(subject, candidate)
        assessed_value = _to_decimal(getattr(candidate, "assessed_value", None))

        distance_meters = getattr(candidate, "distance_meters", None)
        distance_miles: Optional[Decimal] = None
        if distance_meters:
            distance_miles = (Decimal(str(distance_meters)) / Decimal("1609.344")).quantize(Decimal("0.01"))

        candidate_roll_year = candidate.roll.year if getattr(candidate, "roll", None) else None
        candidate_roll_id = candidate.roll_id if getattr(candidate, "roll_id", None) else None
        candidate_style = getattr(candidate, "building_style", None)

        comp_market_group = resolve_market_group(candidate.neighborhood_code) or getattr(candidate, "city_district", None)

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
            assessed_value=assessed_value,
            geom=_ensure_wgs84(candidate.geom),
            metadata={
                "sale_deed_type": getattr(candidate, "comp_deed_type", None),
                "neighborhood_code": candidate.neighborhood_code,
                "city_district": getattr(candidate, "city_district", None),
                "valuation_area": comp_market_group,
                "roll_year": candidate_roll_year,
                "roll_id": candidate_roll_id,
                "assessor_building_style": candidate_style,
                "assessed_value": float(assessed_value) if assessed_value is not None else None,
                "finished_basement_sqft": float(candidate.finished_basement) if candidate.finished_basement else None,
                "unfinished_basement_sqft": (
                    float(candidate.unfinished_basement) if candidate.unfinished_basement else None
                ),
            },
        )
        has_basement = False
        if candidate.finished_basement and candidate.finished_basement > 0:
            has_basement = True
        if candidate.unfinished_basement and candidate.unfinished_basement > 0:
            has_basement = True
        comp_snapshot.metadata["has_basement"] = has_basement

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
                assessed_value=assessed_value.quantize(Decimal("0.01")) if assessed_value is not None else None,
                sale_date=_safe_date(getattr(candidate, "comp_sale_date", None)),
                distance_meters=float(distance_meters) if distance_meters else None,
                distance_miles=distance_miles,
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
        "adjusted_price": lambda c: c.sale_price,
        "distance": lambda c: c.distance_miles if c.distance_miles is not None else Decimal("0"),
        "sale_date": lambda c: c.sale_date or dt.date.min,
        "gpa": lambda c: Decimal("0"),
        "total_adjustment": lambda c: Decimal("0"),
    }
    key_func = key_map.get(sort_field, key_map["distance"])
    return sorted(comparables, key=key_func, reverse=reverse)


def _compute_difference_flags(subject: PropertySnapshot, candidate: Assessor) -> Dict[str, bool]:
    """
    Compare basic property characteristics to flag notable deltas without applying adjustments.
    """
    flags: Dict[str, bool] = {}
    field_pairs = {
        "living_area": ("living_area", "living_area"),
        "bedrooms": ("bedrooms", "bedrooms"),
        "bathrooms": ("bathrooms", "bathrooms"),
        "garage_sqft": ("garage_sqft", "garage_sqft"),
        "acres": ("acres", "acres"),
        "year_built": ("year_built", "year_built"),
    }
    for key, (subject_attr, candidate_attr) in field_pairs.items():
        subj_val = _to_decimal(getattr(subject, subject_attr, None))
        comp_val = _to_decimal(getattr(candidate, candidate_attr, None))
        threshold = DIFFERENCE_ALERTS.get(key, Decimal("0"))
        if subj_val is None or comp_val is None:
            flags[key] = False
            continue
        flags[key] = abs(subj_val - comp_val) >= threshold
    return flags


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
