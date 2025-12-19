from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.contrib.gis.measure import D
from django.db.models import F, OuterRef, Q, Subquery, Window
from django.db.models.functions import RowNumber
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance, Transform

from .models import Assessor, Sales
from .improvement_utils import rollup_for_parcel
from .valuation_areas import resolve_market_group
from openskagit.models import AdjustmentCoefficient


DEFAULT_COMPARABLE_LIMIT = 16
MAX_COMPARABLE_LIMIT = 24
DEFAULT_RADIUS_METERS = 3000
DEFAULT_MAX_SALE_AGE_DAYS = 540
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


def _normalize_subject_geom(subject: PropertySnapshot) -> GEOSGeometry:
    """
    Ensure the subject snapshot stores a WGS84 geometry for reuse.
    """
    normalized = _ensure_wgs84(getattr(subject, "geom", None))
    if normalized is None:
        raise ValueError("Subject parcel missing geometry.")
    subject.geom = normalized
    return normalized


def _sale_date_cutoff(max_sale_age_days: Optional[int]) -> Optional[dt.datetime]:
    if not max_sale_age_days:
        return None
    try:
        days = int(max_sale_age_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return timezone.now() - dt.timedelta(days=days)


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
    lot_acres: Optional[Decimal]
    bedrooms: Optional[Decimal]
    bathrooms: Optional[Decimal]
    year_built: Optional[int]
    effective_year_built: Optional[int]
    garage_sqft: Optional[Decimal]
    acres: Optional[Decimal]
    assessed_value: Optional[Decimal]
    geom: Optional[GEOSGeometry]
    metadata: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_assessor_row(cls, row, *, rollup_cache=None, address_override=None):
        """
        Build a PropertySnapshot from an Assessor row used in comparable selection.
        Mirrors load_subject(), ensuring consistent metadata for CMA and adjustments.
        """
        snapshot_geom = getattr(row, "geom", None)
        if snapshot_geom is not None:
            snapshot_geom = _ensure_wgs84(snapshot_geom)

        roll = getattr(row, "roll", None)
        roll_year = roll.year if roll else None
        roll_id = getattr(row, "roll_id", None)

        valuation_area = resolve_market_group(getattr(row, "neighborhood_code", None)) or getattr(
            row, "city_district", None
        )

        market_value = current_property_value(row)

        metadata: Dict[str, Optional[object]] = {
            "neighborhood_code": getattr(row, "neighborhood_code", None),
            "neighborhood": getattr(row, "neighborhood_code_description", None),
            "land_use_code": getattr(row, "land_use_code", None),
            "city_district": getattr(row, "city_district", None),
            "valuation_area": valuation_area,
            "valuation_subarea": getattr(row, "neighborhood_code", None),
            "assessment_roll_year": roll_year,
            "roll_year": roll_year,
            "roll_id": roll_id,
            "assessor_building_style": getattr(row, "building_style", None),
            "assessed_value": float(market_value) if market_value is not None else None,
            "total_market_value": float(getattr(row, "total_market_value", None)) if getattr(row, "total_market_value", None) is not None else None,
            "county_assessed_value": float(getattr(row, "assessed_value", None)) if getattr(row, "assessed_value", None) is not None else None,
            "finished_basement_sqft": float(row.finished_basement) if getattr(row, "finished_basement", None) else None,
            "unfinished_basement_sqft": float(row.unfinished_basement) if getattr(row, "unfinished_basement", None) else None,
        }

        calculated_sqft = _to_decimal(getattr(row, "calculated_square_footage", None))
        metadata["calculated_square_footage"] = (
            float(calculated_sqft) if calculated_sqft is not None else None
        )

        age_value: Optional[int] = None
        effective_year = int(row.eff_year_built) if row.eff_year_built else None
        if effective_year:
            age_value = max(0, timezone.now().year - effective_year)

        garage_sqft_val = getattr(row, "garage_sqft", None)
        has_garage = bool(_to_decimal(garage_sqft_val) not in (None, Decimal("0")))
        has_basement = bool(getattr(row, "finished_basement", 0) or getattr(row, "unfinished_basement", 0))

        address_value = (
            address_override
            if address_override is not None
            else _clean_address(getattr(row, "address", None)) or ""
        )

        snapshot = cls(
            parcel_number=row.parcel_number,
            address=address_value,
            sale_price=_to_decimal(getattr(row, "comp_sale_price", None)),
            sale_date=_safe_date(getattr(row, "comp_sale_date", None)),
            property_type=row.property_type,
            living_area=_preferred_living_area(row),
            lot_acres=_to_decimal(row.acres),
            bedrooms=_to_decimal(row.bedrooms),
            bathrooms=_to_decimal(row.bathrooms),
            year_built=int(row.year_built) if row.year_built else None,
            effective_year_built=effective_year,
            garage_sqft=_to_decimal(row.garage_sqft),
            acres=_to_decimal(row.acres),
            assessed_value=market_value,
            geom=snapshot_geom,
            metadata=metadata,
        )

        snapshot.metadata.update(
            {
                "age": age_value,
                "quality_score": getattr(row, "quality_score", None),
                "condition_score": getattr(row, "condition_score", None),
                "has_garage": has_garage,
                "has_basement": has_basement,
            }
        )

        # Improvement rollup
        if rollup_cache is not None:
            snapshot.metadata["improvements"] = get_improvement_rollup(
                row.parcel_number,
                roll_year=roll_year,
                roll_id=roll_id,
                assessor_building_style=getattr(row, "building_style", None),
                cache=rollup_cache,
            )

        return snapshot

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "parcel_number": self.parcel_number,
            "address": self.address,
            "sale_price": str(self.sale_price) if self.sale_price is not None else None,
            "sale_date": self.sale_date.isoformat() if self.sale_date else None,
            "property_type": self.property_type,
            "living_area": float(self.living_area) if self.living_area is not None else None,
            "lot_acres": float(self.lot_acres) if self.lot_acres is not None else None,
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
class ComparableScore:
    location_score: Decimal
    time_score: Decimal
    physical_score: Decimal
    total_score: Decimal

    @classmethod
    def from_components(cls, location: float, time: float, physical: float) -> "ComparableScore":
        loc_val = Decimal(str(max(0.0, min(1.0, location or 0.0))))
        time_val = Decimal(str(max(0.0, min(1.0, time or 0.0))))
        phys_val = Decimal(str(max(0.0, min(1.0, physical or 0.0))))
        total = (Decimal("0.40") * loc_val) + (Decimal("0.30") * time_val) + (Decimal("0.30") * phys_val)
        return cls(
            location_score=loc_val,
            time_score=time_val,
            physical_score=phys_val,
            total_score=total,
        )


@dataclass
class ComparableResult:
    snapshot: PropertySnapshot
    sale_price: Optional[Decimal]
    sale_date: Optional[dt.date]
    assessed_value: Optional[Decimal]
    distance_meters: Optional[float]
    distance_miles: Optional[Decimal]
    difference_flags: Dict[str, bool]
    inclusion_rank: int
    score: Optional[ComparableScore] = None

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, PropertySnapshot):
            raise TypeError("ComparableResult.snapshot must be a PropertySnapshot instance.")

    def marker_payload(self) -> Dict[str, object]:
        geom = self.snapshot.geom
        if not geom:
            return {}
        return {
            "parcel_number": self.snapshot.parcel_number,
            "lat": geom.y,
            "lon": geom.x,
            "sale_price": float(self.sale_price) if self.sale_price is not None else None,
            "assessed_value": float(self.assessed_value) if self.assessed_value is not None else None,
            "address": self.snapshot.address,
            "rank": self.inclusion_rank,
        }


@dataclass
class ComputationResult:
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


def _preferred_living_area(record: Optional[object]) -> Optional[Decimal]:
    if record is None:
        return None
    for attr in ("calculated_square_footage", "living_area"):
        if hasattr(record, attr):
            area_value = _to_decimal(getattr(record, attr))
            if area_value is not None:
                return area_value
    return None


def current_property_value(record: Optional[object]) -> Optional[Decimal]:
    """
    Prefer the assessor's total_market_value but fall back to assessed_value when needed.
    """
    if record is None:
        return None
    for attr in ("total_market_value", "assessed_value"):
        if hasattr(record, attr):
            attr_value = getattr(record, attr)
            if attr_value not in (None, ""):
                return _to_decimal(attr_value)
    return None


def _safe_date(value: Optional[dt.datetime]) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def _clean_address(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    lowered = s.lower()
    if lowered in {"nan", "nan nan, nan", "none", "null", "n/a"}:
        return None
    return s


def _metadata_dict(snapshot: PropertySnapshot) -> Dict[str, object]:
    metadata = getattr(snapshot, "metadata", {})
    if isinstance(metadata, dict):
        return metadata
    return {}


def _subject_valuation_date(subject: PropertySnapshot) -> dt.date:
    metadata = _metadata_dict(subject)
    roll_year = metadata.get("assessment_roll_year")
    if roll_year is not None:
        try:
            year = int(roll_year)
            return dt.date(year, 1, 1)
        except (TypeError, ValueError):
            pass
    if subject.sale_date:
        return subject.sale_date
    return timezone.now().date()


def _compute_location_score(
    subject: PropertySnapshot,
    comparable: PropertySnapshot,
    distance_meters: Optional[float],
    search_radius: Optional[float],
) -> float:
    subject_meta = _metadata_dict(subject)
    comp_meta = _metadata_dict(comparable)
    subject_area = subject_meta.get("valuation_area")
    comp_area = comp_meta.get("valuation_area")
    if subject_area and comp_area and subject_area != comp_area:
        return 0.0

    subject_nbhd = subject_meta.get("neighborhood_code")
    comp_nbhd = comp_meta.get("neighborhood_code")
    subject_city = subject_meta.get("city_district")
    comp_city = comp_meta.get("city_district")

    try:
        distance_val = float(distance_meters) if distance_meters is not None else None
    except (TypeError, ValueError):
        distance_val = None

    radius = float(search_radius or DEFAULT_RADIUS_METERS or 1.0)
    if radius <= 0:
        radius = float(DEFAULT_RADIUS_METERS)

    base = 0.8 if distance_val is None else max(0.0, 1.0 - min(distance_val, radius) / radius)
    if subject_nbhd and comp_nbhd and subject_nbhd == comp_nbhd:
        base += 0.2
    elif subject_city and comp_city and subject_city == comp_city:
        base += 0.05

    return max(0.0, min(1.0, base))


def _compute_time_score(sale_date: Optional[dt.date], valuation_date: dt.date) -> float:
    if not sale_date or not valuation_date:
        return 0.0
    days = abs((valuation_date - sale_date).days)
    months = days / 30.4375
    if months <= 3:
        return 1.0
    if months <= 6:
        return 0.9
    if months <= 12:
        return 0.7
    if months <= 18:
        return 0.5
    if months <= 24:
        return 0.3
    return 0.0


def _float_value(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
def _compute_physical_score(
    subject: PropertySnapshot,
    comparable: PropertySnapshot,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    # Use regression-based weights if provided; otherwise default to legacy scheme.
    weights = weights or {}
    w_area      = weights.get("area", 0.25)
    w_baths     = weights.get("baths", 0.15)
    w_beds      = weights.get("beds", 0.10)
    w_lot       = weights.get("lot", 0.15)
    w_age       = weights.get("age", 0.10)
    w_garage    = weights.get("garage", 0.05)
    w_basement  = weights.get("basement", 0.05)
    w_quality   = weights.get("quality", 0.075)
    w_condition = weights.get("condition", 0.075)
    w_view      = weights.get("view", 0.0)  # currently unused until we add view similarity

    subject_meta = _metadata_dict(subject)
    comp_meta = _metadata_dict(comparable)

    def accumulate(weight: float, similarity: Optional[float], *, accumulator: Dict[str, float]) -> None:
        if similarity is None:
            return
        accumulator["score"] += weight * similarity
        accumulator["weight"] += weight

    totals: Dict[str, float] = {"score": 0.0, "weight": 0.0}

    # --- AREA ---
    subj_area = _float_value(subject.living_area)
    comp_area = _float_value(comparable.living_area)
    if subj_area is not None and comp_area is not None and subj_area > 0:
        scale = max(subj_area * 0.2, 300.0)
        similarity = math.exp(-abs(subj_area - comp_area) / scale)
        accumulate(w_area, similarity, accumulator=totals)

    # --- BATHS ---
    subj_baths = _float_value(subject.bathrooms)
    comp_baths = _float_value(comparable.bathrooms)
    if subj_baths is not None and comp_baths is not None:
        similarity = math.exp(-abs(subj_baths - comp_baths) / 0.75)
        accumulate(w_baths, similarity, accumulator=totals)

    # --- BEDS ---
    subj_beds = _float_value(subject.bedrooms)
    comp_beds = _float_value(comparable.bedrooms)
    if subj_beds is not None and comp_beds is not None:
        similarity = math.exp(-abs(subj_beds - comp_beds) / 1.0)
        accumulate(w_beds, similarity, accumulator=totals)

    # --- LOT SIZE (ACRES) ---
    subj_lot = _float_value(subject.acres or subject.lot_acres)
    comp_lot = _float_value(comparable.acres or comparable.lot_acres)
    if subj_lot is not None and comp_lot is not None and subj_lot > 0:
        scale = max(subj_lot * 0.25, 0.1)
        similarity = math.exp(-abs(subj_lot - comp_lot) / scale)
        accumulate(w_lot, similarity, accumulator=totals)

    # --- AGE ---
    subj_age = _float_value(subject_meta.get("age"))
    comp_age = _float_value(comp_meta.get("age"))
    if subj_age is not None and comp_age is not None:
        similarity = math.exp(-abs(subj_age - comp_age) / 10.0)
        accumulate(w_age, similarity, accumulator=totals)

    # --- GARAGE ---
    subj_garage = subject_meta.get("has_garage")
    comp_garage = comp_meta.get("has_garage")
    if subj_garage is not None and comp_garage is not None:
        similarity = 1.0 if bool(subj_garage) == bool(comp_garage) else 0.5
        accumulate(w_garage, similarity, accumulator=totals)

    # --- BASEMENT ---
    subj_basement = subject_meta.get("has_basement")
    comp_basement = comp_meta.get("has_basement")
    if subj_basement is not None and comp_basement is not None:
        similarity = 1.0 if bool(subj_basement) == bool(comp_basement) else 0.6
        accumulate(w_basement, similarity, accumulator=totals)

    # --- QUALITY ---
    subj_quality = subject_meta.get("quality_score")
    comp_quality = comp_meta.get("quality_score")
    if subj_quality is not None and comp_quality is not None:
        similarity = (
            1.0
            if str(subj_quality).strip().lower() == str(comp_quality).strip().lower()
            else 0.6
        )
        accumulate(w_quality, similarity, accumulator=totals)

    # --- CONDITION ---
    subj_condition = subject_meta.get("condition_score")
    comp_condition = comp_meta.get("condition_score")
    if subj_condition is not None and comp_condition is not None:
        similarity = (
            1.0
            if str(subj_condition).strip().lower() == str(comp_condition).strip().lower()
            else 0.6
        )
        accumulate(w_condition, similarity, accumulator=totals)

    # TODO: when you’re ready, add a view similarity that uses w_view.

    if totals["weight"] == 0:
        return 0.0

    return max(0.0, min(1.0, totals["score"] / totals["weight"]))


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

    market_value = current_property_value(assessor)
    calculated_sqft = _to_decimal(assessor.calculated_square_footage)

    snapshot = PropertySnapshot(
        parcel_number=assessor.parcel_number,
        address=assessor.address or "Unknown address",
        sale_price=_to_decimal(sale_row.sale_price if sale_row else assessor.sale_price),
        sale_date=_safe_date(sale_row.sale_date if sale_row else assessor.sale_date),
        property_type=assessor.property_type,
        living_area=_preferred_living_area(assessor),
        lot_acres=_to_decimal(assessor.acres),
        bedrooms=_to_decimal(assessor.bedrooms),
        bathrooms=_to_decimal(assessor.bathrooms),
        year_built=int(assessor.year_built) if assessor.year_built else None,
        effective_year_built=int(assessor.eff_year_built) if assessor.eff_year_built else None,
        garage_sqft=_to_decimal(assessor.garage_sqft),
        acres=_to_decimal(assessor.acres),
        assessed_value=market_value,
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
        "assessed_value": float(market_value) if market_value is not None else None,
        "total_market_value": float(assessor.total_market_value) if assessor.total_market_value is not None else None,
        "county_assessed_value": float(assessor.assessed_value) if assessor.assessed_value is not None else None,
        "finished_basement_sqft": float(assessor.finished_basement) if assessor.finished_basement else None,
        "unfinished_basement_sqft": float(assessor.unfinished_basement) if assessor.unfinished_basement else None,
        "quality_score": getattr(assessor, "quality_score", None),
        "condition_score": getattr(assessor, "condition_score", None),
        "calculated_square_footage": float(calculated_sqft) if calculated_sqft is not None else None,
        "has_garage": bool(assessor.garage_sqft),
            "has_basement": bool(
                (assessor.finished_basement or 0) > 0 or (assessor.unfinished_basement or 0) > 0
            ),
            "lot_acres": float(assessor.acres) if assessor.acres is not None else None,
            "age": (timezone.now().year - int(assessor.eff_year_built)) if assessor.eff_year_built else None,
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


def _base_queryset(
    subject: PropertySnapshot,
    radius_meters: Optional[float] = None,
    *,
    max_sale_age_days: Optional[int] = DEFAULT_MAX_SALE_AGE_DAYS,
) -> Iterable[Assessor]:
    # Subqueries for SALES table
    sale_sq_base = Sales.objects.filter(
        parcel_number=OuterRef("parcel_number"),
        sale_type__iregex=r"^\s*valid sale\s*$",
    ).order_by("-sale_date")

    sale_sq_price = Subquery(sale_sq_base.values("sale_price")[:1])
    sale_sq_date = Subquery(sale_sq_base.values("sale_date")[:1])
    sale_sq_deed = Subquery(sale_sq_base.values("deed_type")[:1])

    # Subject geography (point) normalized to WGS84
    subject_geom = _normalize_subject_geom(subject)

    # -----------------------------------------------------
    # BASE QUERYSET – SPATIAL PRUNING FIRST (very fast)
    # -----------------------------------------------------
    qs = (
        Assessor.objects
        .filter(geom__isnull=False, roll__year=2025, property_type="R")
        .annotate(geom_4326=Transform("geom", WGS84_SRID))
    )

    if radius_meters is not None:
        qs = qs.filter(
            geom_4326__distance_lte=(
                subject_geom,
                D(m=radius_meters),
            )
        )

    distance_expr = Distance("geom_4326", subject_geom, spheroid=True)
    qs = qs.annotate(
        distance_sort=distance_expr,
        distance_meters=distance_expr,
    )

    # Only select fields needed later
    qs = qs.only(
        "parcel_number",
        "address",
        "calculated_square_footage",
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
        "total_market_value",
        "quality_score",
        "condition_score",
        "condition_code",
    )

    # Exclude subject parcel
    qs = qs.exclude(parcel_number=subject.parcel_number)

    # Attach sales subqueries
    qs = qs.annotate(
        comp_sale_price=sale_sq_price,
        comp_sale_date=sale_sq_date,
        comp_deed_type=sale_sq_deed,
    ).filter(comp_sale_price__gt=0)

    sale_cutoff = _sale_date_cutoff(max_sale_age_days)
    if sale_cutoff is not None:
        qs = qs.filter(comp_sale_date__isnull=False, comp_sale_date__gte=sale_cutoff)
    else:
        qs = qs.filter(comp_sale_date__isnull=False)
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
    *,
    filters=None,
    excluded=None,
    sort_field="score",
    sort_direction="desc",
    limit=DEFAULT_COMPARABLE_LIMIT,
    load_improvements=False,
    rollup_cache=None,
    radius_meters=None,
    max_sale_age_days: Optional[int] = DEFAULT_MAX_SALE_AGE_DAYS,
    oversample_factor: int = 2,
):
    """
    Optimized comparable selection with:
    - SRID-safe distance calculation
    - consistent recency filtering (default 540 days)
    - safe filter handling
    - improved ComparableResult construction
    """

    geom = _normalize_subject_geom(subject)
    valuation_date = _subject_valuation_date(subject)
    subject_metadata = _metadata_dict(subject)
    subject_neighborhood = subject_metadata.get("neighborhood_code")
    subject_city = subject_metadata.get("city_district")
    subject_land_use = (subject_metadata.get("land_use_code") or "").strip()

    # ---------------------------------------
    # Determine search radius
    # ---------------------------------------
    if radius_meters is not None:
        search_radius = radius_meters
    else:
        filter_radius = getattr(filters, "radius_meters", None)
        search_radius = filter_radius if filter_radius else DEFAULT_RADIUS_METERS

    # ---------------------------------------
    # 1. Base queryset: spatial prune only
    # ---------------------------------------
    excluded = excluded or []

    qs = (
        Assessor.objects
        .filter(
            geom__isnull=False,
            property_type="R",
        )
        .exclude(parcel_number=subject.parcel_number)
        .exclude(parcel_number__in=excluded)
        .annotate(
            geom_4326=Transform("geom", WGS84_SRID),
        )
        .select_related("roll")
    )

    qs = (
        qs.filter(
            bedrooms__isnull=False,
            bathrooms__isnull=False,
            year_built__isnull=False,
        )
        .filter(
            Q(calculated_square_footage__isnull=False) | Q(living_area__isnull=False)
        )
    )

    if subject_land_use:
        qs = qs.filter(land_use_code__iexact=subject_land_use)

    if search_radius is not None:
        qs = qs.filter(
            geom_4326__distance_lte=(
                geom,
                D(m=search_radius),
            )
        )

    distance_expr = Distance("geom_4326", geom, spheroid=True)
    qs = qs.annotate(
        distance_sort=distance_expr,
        distance_meters=distance_expr,
    )

    # ---------------------------------------
    # 2. Structural filters (safe access)
    # ---------------------------------------
    min_acres = getattr(filters, "min_acres", None)
    max_acres = getattr(filters, "max_acres", None)
    min_year  = getattr(filters, "min_year", None)
    max_year  = getattr(filters, "max_year", None)

    if min_acres is not None:
        qs = qs.filter(acres__gte=min_acres)
    if max_acres is not None:
        qs = qs.filter(acres__lte=max_acres)

    if min_year is not None:
        qs = qs.filter(eff_year_built__gte=min_year)
    if max_year is not None:
        qs = qs.filter(eff_year_built__lte=max_year)

    # ---------------------------------------
    # 3. Annotate: latest valid sale per parcel
    # ---------------------------------------
    sale_sq = (
        Sales.objects
        .filter(
            parcel_number=OuterRef("parcel_number"),
            sale_type__iregex=r"^\s*valid sale\s*$",
        )
        .order_by("-sale_date")
    )

    qs = qs.annotate(
        comp_sale_price=Subquery(sale_sq.values("sale_price")[:1]),
        comp_sale_date=Subquery(sale_sq.values("sale_date")[:1]),
        comp_deed_type=Subquery(sale_sq.values("deed_type")[:1]),
    ).exclude(comp_sale_price__isnull=True)

    # ---------------------------------------
    # 4. Recency filtering
    # ---------------------------------------
    sale_cutoff = _sale_date_cutoff(max_sale_age_days)
    if sale_cutoff is not None:
        qs = qs.filter(comp_sale_date__isnull=False, comp_sale_date__gte=sale_cutoff)
    else:
        qs = qs.filter(comp_sale_date__isnull=False)

    # ---------------------------------------
    # 5. Sorting
    # ---------------------------------------
    normalized_sort = (sort_field or "").strip().lower()
    if normalized_sort == "sale_price":
        order_by = ("-comp_sale_price",)
    elif normalized_sort == "sale_date":
        order_by = ("-comp_sale_date",)
    else:
        order_by = ("distance_meters",)

    if (sort_direction or "").lower() == "desc":
        order_by = tuple(
            f"-{f}" if not f.startswith("-") else f[1:]
            for f in order_by
        )

    oversample_factor = max(1, int(oversample_factor or 1))
    distinct_order = ("parcel_number",) + order_by
    qs = qs.order_by(*distinct_order).distinct("parcel_number")

    total_needed = limit * oversample_factor
    raw_rows: List[Assessor] = []
    fetched_parcels: set[str] = set()

    def _fetch_rows(base_qs, needed: int) -> None:
        if needed <= 0:
            return
        rows = list(base_qs[:needed])
        for row in rows:
            parcel = getattr(row, "parcel_number", None)
            if parcel:
                fetched_parcels.add(parcel)
        raw_rows.extend(rows)

    if subject_neighborhood:
        _fetch_rows(qs.filter(neighborhood_code=subject_neighborhood), total_needed)

    if len(raw_rows) < total_needed and subject_city:
        remaining = total_needed - len(raw_rows)
        city_qs = qs.filter(city_district=subject_city)
        if fetched_parcels:
            city_qs = city_qs.exclude(parcel_number__in=list(fetched_parcels))
        _fetch_rows(city_qs, remaining)

    if len(raw_rows) < total_needed:
        remaining = total_needed - len(raw_rows)
        fallback_qs = qs
        if fetched_parcels:
            fallback_qs = fallback_qs.exclude(parcel_number__in=list(fetched_parcels))
        _fetch_rows(fallback_qs, remaining)

    # ---------------------------------------
    # 6. Build ComparableResult structures
    # ---------------------------------------
        # Regression-based physical weights for this subject's market group
    coeffs = _load_coefficients_for_subject(subject)
    reg_weights = _regression_based_weights(coeffs) if coeffs else {}

    comps: List[ComparableResult] = []
    seen_parcels: set[str] = set()
    for row in raw_rows:
        parcel_id = getattr(row, "parcel_number", None)
        if not parcel_id or parcel_id in seen_parcels:
            continue
        clean_address = _clean_address(getattr(row, "address", None))
        if clean_address is None:
            continue
        snapshot = PropertySnapshot.from_assessor_row(
            row,
            rollup_cache=rollup_cache,
            address_override=clean_address,
        )

        distance_measure = getattr(row, "distance_meters", None)
        distance_value_m = None
        if distance_measure is not None:
            try:
                distance_value_m = float(distance_measure.m)
            except AttributeError:
                distance_value_m = float(distance_measure)

        if distance_value_m is not None:
            snapshot.metadata.setdefault("distance_meters", distance_value_m)

        comp_sale_date = _safe_date(row.comp_sale_date)
        location_score = _compute_location_score(subject, snapshot, distance_value_m, search_radius)
        time_score = _compute_time_score(comp_sale_date, valuation_date)
        physical_score = _compute_physical_score(subject, snapshot, weights=reg_weights)

        score_obj = ComparableScore.from_components(location_score, time_score, physical_score)

        comp = ComparableResult(
            snapshot=snapshot,
            sale_price=row.comp_sale_price,
            assessed_value=current_property_value(row),
            sale_date=comp_sale_date,
            distance_meters=distance_value_m,
            distance_miles=(
                Decimal(str(distance_value_m / 1609.34))
                if distance_value_m is not None else None
            ),
            difference_flags=_compute_difference_flags(subject, row),
            inclusion_rank=len(comps) + 1,
            score=score_obj,
        )

        seen_parcels.add(parcel_id)
        comps.append(comp)

    # ---------------------------------------
    # 7. Sort + prefetch improvements if requested
    # ---------------------------------------
    comps = _sort_comparables(comps, sort_field, sort_direction)
    comps = comps[:limit]

    for idx, comp in enumerate(comps, start=1):
        comp.inclusion_rank = idx

    if load_improvements:
        _prefetch_improvements(comps, rollup_cache)

    return ComputationResult(subject, comps, filters, sort_field, sort_direction)

def _prefetch_improvements(comps, rollup_cache):
    """
    Preload improvements into each ComparableResult.snapshot.metadata["improvements"].
    Avoids N+1 queries.
    """
    for comp in comps:
        snap = comp.snapshot
        if "improvements" not in snap.metadata:
            snap.metadata["improvements"] = get_improvement_rollup(
                snap.parcel_number,
                roll_year=snap.metadata.get("assessment_roll_year"),
                roll_id=snap.metadata.get("roll_id"),
                assessor_building_style=snap.metadata.get("assessor_building_style"),
                cache=rollup_cache,
            )


def _sort_comparables(
    comparables: List[ComparableResult], sort_field: str, sort_direction: str
) -> List[ComparableResult]:
    normalized_field = (sort_field or "").strip().lower()
    normalized_direction = (sort_direction or "").strip().lower()
    if normalized_direction not in {"asc", "desc"}:
        normalized_direction = "desc"

    key_map = {
        "sale_price": lambda c: c.sale_price,
        "adjusted_price": lambda c: c.sale_price,
        "distance": lambda c: c.distance_miles if c.distance_miles is not None else Decimal("0"),
        "sale_date": lambda c: c.sale_date or dt.date.min,
        "gpa": lambda c: Decimal("0"),
        "total_adjustment": lambda c: Decimal("0"),
    }

    def score_key(comp: ComparableResult) -> Tuple[float, float, float, float, int, float]:
        total = float(comp.score.total_score) if comp.score else 0.0
        loc = float(comp.score.location_score) if comp.score else 0.0
        time_comp = float(comp.score.time_score) if comp.score else 0.0
        physical = float(comp.score.physical_score) if comp.score else 0.0
        sale_ord = comp.sale_date.toordinal() if comp.sale_date else 0
        distance = float(comp.distance_miles) if comp.distance_miles is not None else float("inf")
        return (total, loc, time_comp, physical, sale_ord, -distance)

    if normalized_field == "score" or normalized_field not in key_map:
        reverse = normalized_direction != "asc"
        return sorted(comparables, key=score_key, reverse=reverse)

    reverse = normalized_direction == "desc"
    key_func = key_map[normalized_field]
    return sorted(comparables, key=key_func, reverse=reverse)


def _compute_difference_flags(subject: PropertySnapshot, candidate: Assessor) -> Dict[str, bool]:
    """
    Compare basic property characteristics to flag notable deltas without applying adjustments.
    """
    flags: Dict[str, bool] = {}
    field_pairs = {
        "living_area": ("living_area", None),
        "bedrooms": ("bedrooms", "bedrooms"),
        "bathrooms": ("bathrooms", "bathrooms"),
        "garage_sqft": ("garage_sqft", "garage_sqft"),
        "acres": ("acres", "acres"),
        "year_built": ("year_built", "year_built"),
    }
    for key, (subject_attr, candidate_attr) in field_pairs.items():
        if key == "living_area":
            subj_val = _to_decimal(getattr(subject, subject_attr, None))
            comp_val = _preferred_living_area(candidate)
        else:
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

    queryset = _base_queryset(subject, max_sale_age_days=DEFAULT_MAX_SALE_AGE_DAYS)
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

def _regression_based_weights(coeffs: dict[str, float]) -> dict[str, float]:
    """
    Convert regression coefficients into rough importance weights
    for CMA physical similarity.

    - Uses abs(beta) for key terms.
    - Ignores:
        * const
        * price-tier dummies (pt_*)
        * missing_quality (data artifact, not a real attribute)
        * area_time (tiny + weird to interpret in similarity)
    - Returns weights that sum to 1 over the keys we care about.
    """
    # Pull raw betas (0 default if missing)
    b_area   = abs(coeffs.get("log_area", 0.0))
    b_lot    = abs(coeffs.get("log_lot", 0.0))
    b_age    = abs(coeffs.get("log_age", 0.0))
    b_q      = abs(coeffs.get("quality_score", 0.0))
    b_c      = abs(coeffs.get("condition_score", 0.0))
    b_gar    = abs(coeffs.get("has_garage", 0.0))
    b_bas    = abs(coeffs.get("has_basement", 0.0))
    b_view   = abs(coeffs.get("is_view", 0.0))

    raw = {
        "area": b_area,
        "lot": b_lot,
        "age": b_age,
        "quality": b_q,
        "condition": b_c,
        "garage": b_gar,
        "basement": b_bas,
        "view": b_view,
    }

    total = sum(raw.values()) or 1.0

    return {k: v / total for k, v in raw.items()}

def _load_coefficients_for_subject(
    subject: PropertySnapshot,
    run_id: Optional[str] = None,
) -> Dict[str, float]:
    """
    Load regression coefficients for the subject's market group (valuation_area).

    Returns a dict like:
        {
            "const": -3.21,
            "log_area": 0.85,
            "log_lot": 0.12,
            "log_age": -0.03,
            "t": 0.01,
            ...
        }

    If run_id is None, uses the most recent run_id for that market_group.
    """
    metadata = _metadata_dict(subject)
    market_group = metadata.get("valuation_area")

    if not market_group:
        return {}

    qs = AdjustmentCoefficient.objects.filter(market_group=market_group)

    if run_id is not None:
        qs = qs.filter(run_id=run_id)
    else:
        # Pick the latest run for this market_group
        latest = (
            qs.order_by("-created_at")
            .values_list("run_id", flat=True)
            .first()
        )
        if not latest:
            return {}
        qs = qs.filter(run_id=latest)

    coeffs: Dict[str, float] = {}
    for row in qs:
        coeffs[row.term] = row.beta

    return coeffs
