from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry, Polygon, Point
from django.contrib.gis.measure import D
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance, Transform
from django.db.models.functions import Coalesce

from .models import MasterParcel, Sales
from .valuation_areas import resolve_market_group
from openskagit.models import AdjustmentCoefficient


DEFAULT_COMPARABLE_LIMIT = 16
MAX_COMPARABLE_LIMIT = 24
DEFAULT_RADIUS_METERS = 3000
DEFAULT_MAX_SALE_AGE_DAYS = 540
logger = logging.getLogger(__name__)
RollupCache = Dict[str, Dict[str, object]]

WGS84_SRID = 4326

QUALITY_SCORE_LABELS = {
    1: "Low",
    2: "Fair",
    3: "Average",
    4: "Good",
    5: "Very Good",
    6: "Excellent",
}

CONDITION_SCORE_LABELS = {
    1: "Poor",
    2: "Fair",
    3: "Average",
    4: "Good",
    5: "Very Good",
    6: "Excellent",
}


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
    cache: Optional[RollupCache] = None,
    master_parcel: Optional[MasterParcel] = None,
    **_unused: object,
) -> Dict[str, object]:
    """
    Build a lightweight improvement summary directly from the MasterParcel rollups.

    Legacy callers still pass roll_year / roll_id kwargs; we accept **_unused to
    remain source-compatible while ignoring those hints (single current roll now).
    """

    def _area_value(value: Optional[object]) -> Optional[int]:
        try:
            if value in (None, "", "null"):
                return None
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 0:
            return None
        return int(round(numeric))

    def _score_label(score: Optional[object], mapping: Dict[int, str]) -> Optional[str]:
        if score in (None, "", "null"):
            return None
        try:
            idx = int(round(float(score)))
        except (TypeError, ValueError):
            return None
        return mapping.get(idx)

    cache_key = parcel_number
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    parcel = master_parcel
    if parcel is None:
        parcel = MasterParcel.objects.filter(parcel_number=parcel_number).first()
    if parcel is None:
        rollup: Dict[str, object] = {}
    else:
        style_value = parcel.building_style or parcel.buildingstyle
        main_area_sqft = (
            parcel.final_living_area
            or parcel.total_living_area
            or parcel.living_area
        )
        components: List[Dict[str, object]] = []

        def _append_component(
            code: str,
            label: str,
            area_value: Optional[object],
            *,
            count_value: Optional[object] = None,
            category: str = "other",
        ) -> None:
            sqft = _area_value(area_value)
            count: Optional[int]
            if count_value in (None, "", "null"):
                count = None
            else:
                try:
                    count = int(count_value)
                except (TypeError, ValueError):
                    count = None
            if sqft is None and count in (None, 0):
                return
            components.append(
                {
                    "code": code,
                    "label": label,
                    "count": count,
                    "total_sqft": sqft,
                    "category": category,
                }
            )

        _append_component(
            "GARAGE",
            "Garage",
            parcel.final_garage_area or parcel.total_garage_area or parcel.garagesqft,
            category="garage",
        )
        _append_component(
            "DECK",
            "Deck",
            parcel.total_deck_area,
            category="amenity",
        )
        _append_component(
            "PORCH",
            "Porch",
            parcel.total_porch_area,
            category="amenity",
        )
        _append_component(
            "BASEMENT",
            "Basement",
            parcel.total_basement_area,
            category="home",
        )
        _append_component(
            "SHOP",
            "Shop / Outbuilding",
            parcel.total_shop_area,
            count_value=parcel.total_shop_count,
            category="outbuilding",
        )
        _append_component(
            "SHED",
            "Shed",
            parcel.total_shed_area,
            count_value=parcel.total_shed_count,
            category="outbuilding",
        )
        if parcel.has_pool:
            _append_component(
                "POOL",
                "Pool",
                None,
                count_value=1,
                category="amenity",
            )

        rollup = {
            "style": style_value,
            "quality": _score_label(parcel.quality_score, QUALITY_SCORE_LABELS),
            "quality_code": None,
            "condition": _score_label(parcel.condition_score, CONDITION_SCORE_LABELS),
            "condition_code": None,
            "main_area": {
                "total_sqft": _area_value(main_area_sqft),
                "by_story": {},
            },
            "components": components,
            "primary": {
                "code": "HOME",
                "label": style_value or "Primary Home",
                "building_style": style_value,
                "total_sqft": _area_value(main_area_sqft),
                "category": "home",
            },
        }

    if cache is not None:
        cache[cache_key] = rollup
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
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    point: Optional[Point] = None
    metadata: Dict[str, object] = field(default_factory=dict)

    def display_point(self) -> Optional[Point]:
        if self.point is not None:
            return self.point
        candidate = _geometry_display_point(self.geom)
        if candidate is None and self.latitude is not None and self.longitude is not None:
            try:
                candidate = Point(float(self.longitude), float(self.latitude), srid=WGS84_SRID)
            except (TypeError, ValueError):
                candidate = None
        self.point = candidate
        return self.point

    def _metadata_dict(self) -> Dict[str, object]:
        return self.metadata if isinstance(self.metadata, dict) else {}

    @property
    def neighborhood_code(self) -> Optional[str]:
        """
        Surface the best-known neighborhood identifier for template/view helpers.
        """
        metadata = self._metadata_dict()
        raw_code = metadata.get("neighborhood_code")
        if not raw_code:
            assessor_meta = metadata.get("assessor")
            if isinstance(assessor_meta, dict):
                raw_code = assessor_meta.get("neighborhoodcode") or assessor_meta.get("neighborhood_code")
        if not raw_code:
            raw_code = metadata.get("neighborhood")
        if isinstance(raw_code, str):
            raw_code = raw_code.strip() or None
        return raw_code

    @property
    def neighborhood_description(self) -> Optional[str]:
        metadata = self._metadata_dict()
        desc = metadata.get("neighborhood") or metadata.get("neighborhood_description")
        if isinstance(desc, str):
            desc = desc.strip() or None
        return desc

    @classmethod
    def from_parcel_row(cls, row, *, rollup_cache=None, address_override=None):
        """
        Build a PropertySnapshot from a MasterParcel row used in comparable selection.
        Mirrors load_subject(), ensuring consistent metadata for CMA and adjustments.
        """
        geom_rel = getattr(row, "geometry", None)
        geom_lat = _float_value(getattr(geom_rel, "latitude", None)) if geom_rel else None
        geom_lon = _float_value(getattr(geom_rel, "longitude", None)) if geom_rel else None

        snapshot_geom = None
        try:
            snapshot_geom = _extract_subject_geometry(row)
        except ValueError:
            snapshot_geom = None
        display_point = _geometry_display_point(snapshot_geom)
        if display_point is None and geom_lat is not None and geom_lon is not None:
            try:
                display_point = Point(float(geom_lon), float(geom_lat), srid=WGS84_SRID)
            except (TypeError, ValueError):
                display_point = None

        valuation_area = resolve_market_group(getattr(row, "hood_code", None)) or getattr(
            row, "city_district", None
        )

        market_value = current_property_value(row)

        metadata: Dict[str, Optional[object]] = {
            "neighborhood_code": getattr(row, "hood_code", None),
            "neighborhood": getattr(row, "hood_description", None),
            "land_use_code": getattr(row, "land_use_code", None),
            "land_use_description": getattr(row, "land_use_description", None),
            "city_district": getattr(row, "city_district", None),
            "valuation_area": valuation_area,
            "valuation_subarea": getattr(row, "hood_code", None),
            "assessor_building_style": getattr(row, "building_style", None)
            or getattr(row, "buildingstyle", None),
            "assessed_value": float(market_value) if market_value is not None else None,
            "total_market_value": float(getattr(row, "total_market_value", None))
            if getattr(row, "total_market_value", None) is not None
            else None,
            "county_assessed_value": float(getattr(row, "assessed_value", None))
            if getattr(row, "assessed_value", None) is not None
            else None,
            "finished_basement_sqft": float(getattr(row, "finishedbasement", None))
            if getattr(row, "finishedbasement", None)
            else None,
            "unfinished_basement_sqft": float(getattr(row, "unfinishedbasement", None))
            if getattr(row, "unfinishedbasement", None)
            else None,
        }

        calculated_sqft = _preferred_living_area(row)
        metadata["calculated_square_footage"] = (
            float(calculated_sqft) if calculated_sqft is not None else None
        )

        effective_year = None
        for attr in ("final_eff_yr_blt", "effective_yr_blt", "eff_year_built"):
            value = getattr(row, attr, None)
            if value:
                try:
                    effective_year = int(value)
                    break
                except (TypeError, ValueError):
                    continue

        age_value: Optional[int] = None
        if effective_year:
            age_value = max(0, timezone.now().year - effective_year)

        garage_sqft_val = (
            getattr(row, "final_garage_area", None)
            or getattr(row, "total_garage_area", None)
            or getattr(row, "garagesqft", None)
        )
        has_garage = bool(_to_decimal(garage_sqft_val) not in (None, Decimal("0")))
        has_basement = bool(
            getattr(row, "total_basement_area", None)
            or getattr(row, "finishedbasement", None)
            or getattr(row, "unfinishedbasement", None)
        )

        address_value = (
            address_override
            if address_override is not None
            else _clean_address(getattr(row, "situs_address", None)) or ""
        )

        living_area = _preferred_living_area(row)
        year_built_value = None
        for attr in ("final_year_built", "year_built"):
            value = getattr(row, attr, None)
            if value:
                try:
                    year_built_value = int(value)
                    break
                except (TypeError, ValueError):
                    continue

        snapshot = cls(
            parcel_number=row.parcel_number,
            address=address_value,
            sale_price=_to_decimal(getattr(row, "comp_sale_price", None)),
            sale_date=_safe_date(getattr(row, "comp_sale_date", None)),
            property_type=getattr(row, "proptype", None),
            living_area=living_area,
            lot_acres=_to_decimal(getattr(row, "acres", None)),
            bedrooms=_to_decimal(getattr(row, "number_of_bedrooms", None)),
            bathrooms=_to_decimal(getattr(row, "total_baths", None)),
            year_built=year_built_value,
            effective_year_built=effective_year,
            garage_sqft=_to_decimal(garage_sqft_val),
            acres=_to_decimal(getattr(row, "acres", None)),
            assessed_value=market_value,
            geom=snapshot_geom,
            latitude=geom_lat,
            longitude=geom_lon,
            point=display_point,
            metadata=metadata,
        )

        snapshot.metadata.update(
            {
                "age": age_value,
                "quality_score": getattr(row, "quality_score", None),
                "condition_score": getattr(row, "condition_score", None),
                "has_garage": has_garage,
                "has_basement": has_basement,
                "has_unit": getattr(row, "has_unit", None),
                "flag_multi_structure": getattr(row, "flag_multi_structure", None),
                "lot_acres": float(getattr(row, "acres", None))
                if getattr(row, "acres", None) is not None
                else None,
            }
        )

        if rollup_cache is not None:
            snapshot.metadata["improvements"] = get_improvement_rollup(
                row.parcel_number,
                cache=rollup_cache,
                master_parcel=row,
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
        self.sale_price = _to_decimal(self.sale_price)
        self.assessed_value = _to_decimal(self.assessed_value)

    def marker_payload(self) -> Dict[str, object]:
        point = self.snapshot.display_point()
        if not point:
            return {}
        return {
            "parcel_number": self.snapshot.parcel_number,
            "lat": point.y,
            "lon": point.x,
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
        sale_values: List[Decimal] = []
        for comp in self.comparables:
            price = _to_decimal(getattr(comp, "sale_price", None))
            if price is not None:
                sale_values.append(price)
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
        subject_point = self.subject.display_point()
        if subject_point:
            markers.append(
                {
                    "type": "subject",
                    "parcel_number": self.subject.parcel_number,
                    "lat": subject_point.y,
                    "lon": subject_point.x,
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
    except (InvalidOperation, ValueError, TypeError):
        return None


def _preferred_living_area(record: Optional[object]) -> Optional[Decimal]:
    if record is None:
        return None
    for attr in ("final_living_area", "total_living_area", "calculated_square_footage", "living_area"):
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
    for key in ("valuation_date", "assessment_date"):
        candidate = metadata.get(key)
        if isinstance(candidate, dt.date):
            return candidate
        if isinstance(candidate, dt.datetime):
            return candidate.date()
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

    `roll_year` is retained for backward compatibility but ignored now that
    MasterParcel represents a single current roll.
    """
    parcel = (
        MasterParcel.objects.select_related("geometry")
        .filter(parcel_number=parcel_number)
        .first()
    )
    if parcel is None:
        raise ValueError(f"Parcel {parcel_number} could not be located")

    geom_rel = getattr(parcel, "geometry", None)
    geom_lat = _float_value(getattr(geom_rel, "latitude", None)) if geom_rel else None
    geom_lon = _float_value(getattr(geom_rel, "longitude", None)) if geom_rel else None

    subject_geom = _extract_subject_geometry(parcel)
    subject_point = _geometry_display_point(subject_geom)

    # Prefer SALES table for last sale details; handle multiple rows safely
    sale_row = (
        Sales.objects.filter(
            parcel_number=parcel.parcel_number,
            sale_type__iregex=r"^\s*valid sale\s*$",
        )
        .order_by("-sale_date")
        .first()
    )

    subject_market_group = resolve_market_group(parcel.hood_code) or parcel.city_district

    market_value = current_property_value(parcel)

    def _first_int(*values: Optional[object]) -> Optional[int]:
        for value in values:
            if value in (None, "", "null"):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    year_built_val = _first_int(parcel.final_year_built, parcel.year_built)
    eff_year_built = _first_int(parcel.final_eff_yr_blt, parcel.effective_yr_blt, parcel.eff_year_built)
    living_area = _preferred_living_area(parcel)
    garage_sqft_val = (
        parcel.final_garage_area or parcel.total_garage_area or parcel.garagesqft
    )
    lot_acres_val = _to_decimal(parcel.acres)

    metadata: Dict[str, Optional[object]] = {
        "neighborhood_code": parcel.hood_code,
        "neighborhood": parcel.hood_description,
        "land_use_code": parcel.land_use_code,
        "land_use_description": parcel.land_use_description,
        "city_district": parcel.city_district,
        "valuation_area": subject_market_group,
        "valuation_subarea": parcel.hood_code,
        "assessor_building_style": parcel.building_style or parcel.buildingstyle,
        "assessed_value": float(market_value) if market_value is not None else None,
        "total_market_value": float(parcel.total_market_value)
        if parcel.total_market_value is not None
        else None,
        "county_assessed_value": float(parcel.assessed_value)
        if parcel.assessed_value is not None
        else None,
        "finished_basement_sqft": float(parcel.finishedbasement)
        if parcel.finishedbasement
        else None,
        "unfinished_basement_sqft": float(parcel.unfinishedbasement)
        if parcel.unfinishedbasement
        else None,
        "quality_score": parcel.quality_score,
        "condition_score": parcel.condition_score,
        "has_garage": bool(garage_sqft_val),
        "has_basement": bool(
            parcel.total_basement_area or parcel.finishedbasement or parcel.unfinishedbasement
        ),
        "lot_acres": float(parcel.acres) if parcel.acres is not None else None,
        "age": (timezone.now().year - eff_year_built) if eff_year_built else None,
        "has_unit": parcel.has_unit,
        "flag_multi_structure": parcel.flag_multi_structure,
    }
    if living_area is not None:
        metadata["calculated_square_footage"] = float(living_area)

    snapshot = PropertySnapshot(
        parcel_number=parcel.parcel_number,
        address=parcel.situs_address or "Unknown address",
        sale_price=_to_decimal(sale_row.sale_price if sale_row else parcel.sale_price),
        sale_date=_safe_date(sale_row.sale_date if sale_row else None),
        property_type=parcel.proptype,
        living_area=living_area,
        lot_acres=lot_acres_val,
        bedrooms=_to_decimal(parcel.number_of_bedrooms),
        bathrooms=_to_decimal(parcel.total_baths),
        year_built=year_built_val,
        effective_year_built=eff_year_built,
        garage_sqft=_to_decimal(garage_sqft_val),
        acres=_to_decimal(parcel.acres),
        assessed_value=market_value,
        geom=subject_geom,
        latitude=geom_lat,
        longitude=geom_lon,
        point=subject_point,
        metadata=metadata,
    )

    # Attach improvement rollup for subject display and downstream pages
    snapshot.metadata["improvements"] = get_improvement_rollup(
        parcel.parcel_number,
        cache=rollup_cache,
        master_parcel=parcel,
    )

    return snapshot


def _extract_subject_geometry(parcel: MasterParcel) -> GEOSGeometry:
    """
    Locate a usable WGS84 geometry for the parcel, trying multiple fallbacks.
    """
    geom_rel = getattr(parcel, "geometry", None)
    candidates: List[Optional[GEOSGeometry]] = []
    if geom_rel is not None:
        candidates.extend(
            [
                getattr(geom_rel, "geom", None),
                getattr(geom_rel, "geom_2926", None),
                getattr(geom_rel, "geom_backup", None),
            ]
        )
    for candidate in candidates:
        if candidate is None:
            continue
        normalized = _ensure_wgs84(candidate)
        if normalized is not None:
            return normalized
    centroid = getattr(geom_rel, "centroid_geog", None) if geom_rel is not None else None
    if centroid is not None:
        try:
            if getattr(centroid, "srid", None) != WGS84_SRID:
                centroid = centroid.clone()
                centroid.transform(WGS84_SRID)
            return centroid
        except Exception:
            pass

    lat = getattr(geom_rel, "latitude", None) if geom_rel is not None else None
    lon = getattr(geom_rel, "longitude", None) if geom_rel is not None else None
    if lat in (None, "") or lon in (None, ""):
        lat = getattr(parcel, "latitude", None)
        lon = getattr(parcel, "longitude", None)
    if lat not in (None, "") and lon not in (None, ""):
        try:
            return Point(float(lon), float(lat), srid=WGS84_SRID)
        except (TypeError, ValueError):
            pass
    raise ValueError("Subject property does not have geospatial coordinates.")


def _geometry_display_point(geom: Optional[GEOSGeometry]) -> Optional[Point]:
    """
    Convert any geometry into a WGS84 point suitable for map display.
    """
    if geom is None:
        return None
    point = geom
    if not isinstance(point, Point):
        try:
            point = geom.centroid
        except Exception:
            return None
    if point is None:
        return None
    point_srid = getattr(point, "srid", None)
    if point_srid is None or point_srid != WGS84_SRID:
        try:
            normalized = GEOSGeometry(point.wkb, srid=point_srid or geom.srid or WGS84_SRID)
            normalized.transform(WGS84_SRID)
            point = normalized
        except Exception:
            return None
    return point


def _base_queryset(
    subject: PropertySnapshot,
    radius_meters: Optional[float] = None,
    *,
    max_sale_age_days: Optional[int] = DEFAULT_MAX_SALE_AGE_DAYS,
) -> Iterable[MasterParcel]:
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
        MasterParcel.objects
        .select_related("geometry")
        .filter(
            Q(geometry__geom__isnull=False)
            | Q(geometry__geom_2926__isnull=False)
            | Q(geometry__centroid_geog__isnull=False)
        )
        .exclude(parcel_number=subject.parcel_number)
    )

    subject_geom_3857: Optional[GEOSGeometry] = None
    try:
        subject_geom_3857 = GEOSGeometry(subject_geom.wkb, srid=subject_geom.srid)
        subject_geom_3857.transform(3857)
    except Exception:
        subject_geom_3857 = None

    subject_geom_2926: Optional[GEOSGeometry] = None
    try:
        subject_geom_2926 = GEOSGeometry(subject_geom.wkb, srid=subject_geom.srid)
        subject_geom_2926.transform(2926)
    except Exception:
        subject_geom_2926 = None

    if radius_meters is not None:
        distance_filter = Q()
        if subject_geom_3857 is not None:
            distance_filter |= Q(
                geometry__geom__distance_lte=(
                    subject_geom_3857,
                    D(m=radius_meters),
                )
            )
        if subject_geom_2926 is not None:
            distance_filter |= Q(
                geometry__geom_2926__distance_lte=(
                    subject_geom_2926,
                    D(m=radius_meters),
                )
            )
        distance_filter |= Q(
            geometry__centroid_geog__distance_lte=(
                subject_geom,
                D(m=radius_meters),
            )
        )
        qs = qs.filter(distance_filter)

    geometry_expr = Coalesce(
        Transform("geometry__geom", WGS84_SRID),
        Transform("geometry__geom_2926", WGS84_SRID),
        "geometry__centroid_geog",
        output_field=gis_models.GeometryField(srid=WGS84_SRID),
    )
    distance_expr = Distance(geometry_expr, subject_geom, spheroid=True)
    qs = qs.annotate(distance_sort=distance_expr, distance_meters=distance_expr)

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
    return qs

def apply_filters(qs: Iterable[MasterParcel], filters: CmaFilters) -> Iterable[MasterParcel]:
    if filters.property_type:
        qs = qs.filter(
            Q(proptype__iexact=filters.property_type)
            | Q(proptype__isnull=True)
            | Q(proptype__exact="")
        )
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
        qs = qs.filter(
            Q(number_of_bedrooms__gte=filters.bedrooms)
            | Q(number_of_bedrooms__isnull=True)
        )
    if filters.bathrooms is not None:
        qs = qs.filter(
            Q(total_baths__gte=filters.bathrooms)
            | Q(total_baths__isnull=True)
        )
    if filters.bbox:
        qs = qs.filter(geometry__geom_2926__within=filters.bbox)
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

    qs = _base_queryset(
        subject,
        radius_meters=search_radius,
        max_sale_age_days=max_sale_age_days,
    ).exclude(parcel_number__in=excluded)

    subject_property_type = (subject.property_type or "").strip()
    if subject_property_type:
        qs = qs.filter(
            Q(proptype__iexact=subject_property_type)
            | Q(proptype__isnull=True)
            | Q(proptype__exact="")
        )
    else:
        qs = qs.filter(
            Q(proptype__iexact="R")
            | Q(proptype__isnull=True)
            | Q(proptype__exact="")
        )

    qs = qs.filter(
        Q(final_year_built__isnull=False)
        | Q(year_built__isnull=False)
        | Q(eff_year_built__isnull=False)
        | Q(effective_yr_blt__isnull=False)
    ).filter(
        Q(final_living_area__isnull=False)
        | Q(total_living_area__isnull=False)
        | Q(living_area__isnull=False)
    )

    if subject_land_use:
        qs = qs.filter(
            Q(land_use_code__iexact=subject_land_use)
            | Q(land_use_code__isnull=True)
            | Q(land_use_code__exact="")
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
        qs = qs.filter(
            Q(final_eff_yr_blt__gte=min_year)
            | Q(effective_yr_blt__gte=min_year)
            | Q(eff_year_built__gte=min_year)
        )
    if max_year is not None:
        qs = qs.filter(
            Q(final_eff_yr_blt__lte=max_year)
            | Q(effective_yr_blt__lte=max_year)
            | Q(eff_year_built__lte=max_year)
        )

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

    # Score sorting happens in-memory after ComparableResult objects are built.
    # Keep DB prefetch order distance-first so retrieval remains stable and broad.
    if normalized_sort in {"sale_price", "sale_date"} and (sort_direction or "").lower() == "desc":
        order_by = tuple(
            f"-{f}" if not f.startswith("-") else f[1:]
            for f in order_by
        )

    oversample_factor = max(1, int(oversample_factor or 1))
    distinct_order = ("parcel_number",) + order_by
    qs = qs.order_by(*distinct_order).distinct("parcel_number")

    total_needed = limit * oversample_factor
    raw_rows: List[MasterParcel] = list(qs[:total_needed])

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
        clean_address = _clean_address(getattr(row, "situs_address", None))
        if clean_address is None:
            continue
        snapshot = PropertySnapshot.from_parcel_row(
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
            sale_price=_to_decimal(getattr(row, "comp_sale_price", None)),
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


def _compute_difference_flags(subject: PropertySnapshot, candidate: MasterParcel) -> Dict[str, bool]:
    """
    Compare basic property characteristics to flag notable deltas without applying adjustments.
    """
    flags: Dict[str, bool] = {}
    field_pairs = {
        "living_area": ("living_area", None),
        "bedrooms": ("bedrooms", "number_of_bedrooms"),
        "bathrooms": ("bathrooms", "total_baths"),
        "garage_sqft": ("garage_sqft", None),
        "acres": ("acres", "acres"),
        "year_built": ("year_built", None),
    }
    for key, (subject_attr, candidate_attr) in field_pairs.items():
        if key == "living_area":
            subj_val = _to_decimal(getattr(subject, subject_attr, None))
            comp_val = _preferred_living_area(candidate)
        elif key == "garage_sqft":
            subj_val = _to_decimal(getattr(subject, subject_attr, None))
            comp_val = _to_decimal(
                getattr(candidate, "final_garage_area", None)
                or getattr(candidate, "total_garage_area", None)
                or getattr(candidate, "garagesqft", None)
            )
        elif key == "year_built":
            subj_val = _to_decimal(getattr(subject, subject_attr, None))
            comp_val = None
            for attr in ("final_year_built", "year_built"):
                value = getattr(candidate, attr, None)
                if value:
                    comp_val = _to_decimal(value)
                    if comp_val is not None:
                        break
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
        poly = Polygon.from_bbox(coords)
        poly.srid = WGS84_SRID
        return poly
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
        try:
            geom = _extract_subject_geometry(candidate)
        except ValueError:
            geom = None
        point = _geometry_display_point(geom)
        if point is None:
            continue
        markers.append(
            {
                "parcel_number": candidate.parcel_number,
                "lat": point.y,
                "lon": point.x,
                "sale_price": float(getattr(candidate, "comp_sale_price", 0)) if getattr(candidate, "comp_sale_price", None) else None,
                "sale_date": _safe_date(getattr(candidate, "comp_sale_date", None)).isoformat()
                if _safe_date(getattr(candidate, "comp_sale_date", None))
                else None,
                "address": getattr(candidate, "situs_address", None),
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
