from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db.models.expressions import RawSQL
from django.utils import timezone

from .models import Assessor


DEFAULT_COMPARABLE_LIMIT = 16
MAX_COMPARABLE_LIMIT = 24


@dataclass(frozen=True)
class AdjustmentRule:
    key: str
    label: str
    attribute: str
    rate: Decimal
    rationale: str
    threshold: Decimal = Decimal("0")
    is_percentage: bool = False


ADJUSTMENT_RULES: Tuple[AdjustmentRule, ...] = (
    AdjustmentRule(
        key="living_area",
        label="Living Area",
        attribute="living_area",
        rate=Decimal("55"),
        rationale="$55 per square foot variance",
        threshold=Decimal("50"),
    ),
    AdjustmentRule(
        key="bedrooms",
        label="Bedrooms",
        attribute="bedrooms",
        rate=Decimal("2500"),
        rationale="$2,500 per bedroom variance",
        threshold=Decimal("1"),
    ),
    AdjustmentRule(
        key="bathrooms",
        label="Bathrooms",
        attribute="bathrooms",
        rate=Decimal("4000"),
        rationale="$4,000 per bathroom variance",
        threshold=Decimal("0.5"),
    ),
    AdjustmentRule(
        key="garage_sqft",
        label="Garage",
        attribute="garage_sqft",
        rate=Decimal("35"),
        rationale="$35 per garage square foot variance",
        threshold=Decimal("20"),
    ),
    AdjustmentRule(
        key="acres",
        label="Lot Size",
        attribute="acres",
        rate=Decimal("35000"),
        rationale="$35k per acre variance",
        threshold=Decimal("0.05"),
    ),
    AdjustmentRule(
        key="year_built",
        label="Year Built",
        attribute="year_built",
        rate=Decimal("1200"),
        rationale="$1,200 per year of effective age",
        threshold=Decimal("3"),
    ),
)


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


def load_subject(parcel_number: str) -> PropertySnapshot:
    try:
        assessor = Assessor.objects.get(parcel_number=parcel_number)
    except Assessor.DoesNotExist as exc:
        raise ValueError(f"Parcel {parcel_number} could not be located") from exc

    if assessor.geom is None:
        raise ValueError("Subject property does not have geospatial coordinates.")

    return PropertySnapshot(
        parcel_number=assessor.parcel_number,
        address=assessor.address or "Unknown address",
        sale_price=_to_decimal(assessor.sale_price),
        sale_date=_safe_date(assessor.sale_date),
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
        },
    )


def _base_queryset(subject: PropertySnapshot) -> Iterable[Assessor]:
    qs = (
        Assessor.objects.filter(geom__isnull=False, sale_price__gt=0)
        .exclude(parcel_number=subject.parcel_number)
        .annotate(
            distance_sort=RawSQL("geom <-> %s", (subject.geom.ewkb,) if subject.geom else (None,)),
            distance_meters=RawSQL(
                "CASE WHEN geom IS NULL OR %s IS NULL THEN NULL "
                "ELSE ST_DistanceSphere(geom::geography, %s::geography) END",
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
        qs = qs.filter(sale_date__gte=start_dt)
    if filters.sale_date_max:
        end_dt = dt.datetime.combine(filters.sale_date_max, dt.time.max)
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt)
        qs = qs.filter(sale_date__lte=end_dt)
    if filters.min_price is not None:
        qs = qs.filter(sale_price__gte=filters.min_price)
    if filters.max_price is not None:
        qs = qs.filter(sale_price__lte=filters.max_price)
    if filters.bedrooms is not None:
        qs = qs.filter(bedrooms__gte=filters.bedrooms)
    if filters.bathrooms is not None:
        qs = qs.filter(bathrooms__gte=filters.bathrooms)
    if filters.bbox:
        qs = qs.filter(geom__within=filters.bbox)
    return qs


def _compute_adjustments(
    subject: PropertySnapshot,
    comp_record: Assessor,
) -> Tuple[List[AdjustmentLine], Dict[str, bool]]:
    adjustments: List[AdjustmentLine] = []
    difference_flags: Dict[str, bool] = {}

    for rule in ADJUSTMENT_RULES:
        subject_value = getattr(subject, rule.attribute)
        comp_value = getattr(comp_record, rule.attribute, None)
        comp_value = _to_decimal(comp_value) if comp_value is not None else None
        if subject_value is None or comp_value is None:
            continue

        subject_decimal = _to_decimal(subject_value)
        if subject_decimal is None:
            continue

        delta = subject_decimal - comp_value
        if delta is None or delta == 0:
            difference_flags[rule.key] = False
            continue

        if rule.threshold and abs(delta) < rule.threshold:
            difference_flags[rule.key] = False
            continue

        amount = delta * rule.rate
        adjustments.append(
            AdjustmentLine(
                code=rule.key,
                label=rule.label,
                amount=amount.quantize(Decimal("0.01")),
                rationale=rule.rationale,
            )
        )

        alert_threshold = DIFFERENCE_ALERTS.get(rule.key)
        difference_flags[rule.key] = bool(alert_threshold and abs(delta) >= alert_threshold)

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
        sale_price = _to_decimal(candidate.sale_price)
        if sale_price is None or sale_price <= 0:
            continue
        auto_adjustments, difference_flags = _compute_adjustments(subject, candidate)
        manual = manual_adjustments.get(candidate.parcel_number, {})
        manual_total = _manual_adjustment_total(manual)
        auto_total = sum((adj.amount for adj in auto_adjustments), start=Decimal("0"))
        adjusted_price = (sale_price + auto_total + manual_total).quantize(Decimal("0.01"))
        gross_total = _gross_adjustment_total(auto_adjustments, manual)
        if sale_price > 0:
            gpa = (gross_total / sale_price * Decimal("100")).quantize(Decimal("0.01"))
        else:
            gpa = Decimal("0")

        distance_meters = getattr(candidate, "distance_meters", None)
        distance_miles: Optional[Decimal] = None
        if distance_meters:
            distance_miles = (Decimal(str(distance_meters)) / Decimal("1609.344")).quantize(Decimal("0.01"))

        comp_snapshot = PropertySnapshot(
            parcel_number=candidate.parcel_number,
            address=candidate.address or "Unknown address",
            sale_price=sale_price,
            sale_date=_safe_date(candidate.sale_date),
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
                "sale_deed_type": candidate.sale_deed_type,
                "neighborhood_code": candidate.neighborhood_code,
            },
        )

        comparables.append(
            ComparableResult(
                snapshot=comp_snapshot,
                sale_price=sale_price.quantize(Decimal("0.01")),
                sale_date=_safe_date(candidate.sale_date),
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
                "sale_price": float(candidate.sale_price) if candidate.sale_price else None,
                "sale_date": _safe_date(candidate.sale_date).isoformat()
                if _safe_date(candidate.sale_date)
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
