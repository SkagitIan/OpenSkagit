from __future__ import annotations

import json
import logging
import functools
import operator
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import requests
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from openskagit import adjustment_engine, appeals, cma
from openskagit.tax import (
    TAX_AI_FAILURE_RETRY_SECONDS,
    _coerce_history_rows,
    _extract_history_tax,
    _extract_history_value,
    _extract_history_year,
    _tax_value_for_year,
    county_etr_insights,
    enqueue_parcel_tax_ai_summary,
    get_cached_parcel_tax_ai_summary,
)
from openskagit.models import (
    AgencyFinancialSnapshot,
    Assessor,
    ExperimentRun,
    MasterParcel,
    ParcelGeometry,
    ParcelHistory,
    RegressionPublishedModel,
    TaxingDistrictLevy,
    YoutubeMeetingAnalysisJob,
)
from openskagit.neighborhood import get_neighborhood_snapshot
from openskagit.services.regression_v1 import (
    DEFAULT_INTERACTION_TERMS,
    DEFAULT_PREDICTORS,
    INTERACTION_DEFINITIONS,
    default_regression_settings,
    load_run_payload,
    parse_settings,
    predict_from_published_payload,
)
from openskagit.services.sedro_woolley_youtube_ingest import _extract_video_id
from openskagit.services.youtube_meeting_analysis import (
    build_analysis_fingerprint,
)
from gastronet.flavor_signals import fetch_flavor_signal_ai_messages


logger = logging.getLogger(__name__)


def _dictfetchall(cursor) -> List[Dict[str, Any]]:
    """
    Return all rows from a cursor as a dict.
    """
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _dictfetchone(cursor) -> Optional[Dict[str, Any]]:
    cols = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(cols, row))


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(val) for key, val in value.items()}
    return value


def _parse_positive_int(value: Optional[str], default: int, *, max_value: Optional[int] = None) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        raise ValidationError("Pagination parameters must be integers.")
    if parsed <= 0:
        raise ValidationError("Pagination parameters must be positive integers.")
    if max_value is not None and parsed > max_value:
        parsed = max_value
    return parsed


def _parse_iso_datetime(value: Optional[str], field_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError({field_name: "Must be an ISO 8601 date or datetime."})


SAO_GISDATA_BASE = "https://portal.sao.wa.gov/gisdata/api/v2"
SAO_BOUNDARY_YEAR_FALLBACK = 2017
SAO_BOUNDARY_YEAR_TTL_SECONDS = 60 * 60 * 12
_SAO_BOUNDARY_YEAR_CACHE: Dict[str, Any] = {"year": None, "fetched_at": None}


def _get_latest_sao_property_tax_year() -> int:
    now = time.time()
    cached_year = _SAO_BOUNDARY_YEAR_CACHE.get("year")
    fetched_at = _SAO_BOUNDARY_YEAR_CACHE.get("fetched_at")
    if cached_year and fetched_at and (now - fetched_at) < SAO_BOUNDARY_YEAR_TTL_SECONDS:
        return cached_year

    url = f"{SAO_GISDATA_BASE}/PropertyTaxBoundaries"
    try:
        resp = requests.get(
            url,
            params={"$select": "year", "$orderby": "year desc", "$top": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        years = [row.get("year") for row in data.get("value", []) if row.get("year")]
        if years:
            year = max(years)
            _SAO_BOUNDARY_YEAR_CACHE.update({"year": year, "fetched_at": now})
            return year
    except Exception:  # pragma: no cover - defensive network fallback
        logger.warning("Failed to fetch SAO property tax boundary year; using fallback.", exc_info=True)

    _SAO_BOUNDARY_YEAR_CACHE.update({"year": SAO_BOUNDARY_YEAR_FALLBACK, "fetched_at": now})
    return SAO_BOUNDARY_YEAR_FALLBACK


def _fetch_sao_mcags_for_point(lat: float, lon: float, year: int) -> List[Dict[str, Any]]:
    url = (
        f"{SAO_GISDATA_BASE}/PropertyTaxBoundaries({year})/boundaries/"
        f"Default.Contains(Latitude={lat},Longitude={lon})"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("value", []) or []


CIVIC_BALANCE_QUARTILE_LABELS = {
    4: "Highest participation density",
    3: "Above-average participation",
    2: "Below-average participation",
    1: "Lowest participation density",
}

SKAGIT_COMMISSIONER_LAYER_QUERY_URL = (
    "https://gis.skagitcountywa.gov/arcgis/rest/services/"
    "Districts/CommissionerDistrictWebMap/MapServer/5/query"
)
SKAGIT_COMMISSIONER_LAYER_DISTRICT_FIELD = "COMMDIST"


@lru_cache(maxsize=8)
def _fetch_skagit_commissioner_district_geometry(district_code: str) -> Dict[str, Any]:
    """
    Pull commissioner district geometry from Skagit County's ArcGIS service.
    """

    response = requests.get(
        SKAGIT_COMMISSIONER_LAYER_QUERY_URL,
        params={
            "where": f"{SKAGIT_COMMISSIONER_LAYER_DISTRICT_FIELD}='{district_code}'",
            "outFields": SKAGIT_COMMISSIONER_LAYER_DISTRICT_FIELD,
            "outSR": 4326,
            "f": "geojson",
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        raise APIException(f"No commissioner district geometry found for district '{district_code}'.")
    geometry = features[0].get("geometry")
    if not isinstance(geometry, dict):
        raise APIException(f"Commissioner district geometry for district '{district_code}' is invalid.")
    return geometry


def _load_skagit_county_boundary_geojson() -> Dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ST_AsGeoJSON(ST_Transform(geom_2926, 4326), 6)
            FROM public.skagit_county_boundary
            LIMIT 1
            """
        )
        row = cursor.fetchone()
    if not row or not row[0]:
        raise APIException("Skagit county boundary geometry is unavailable.")
    try:
        geometry = json.loads(row[0])
    except json.JSONDecodeError as exc:
        raise APIException("Skagit county boundary geometry could not be parsed.") from exc
    if not isinstance(geometry, dict):
        raise APIException("Skagit county boundary geometry is malformed.")
    return geometry


def _rows_to_geojson_features(rows: Sequence[Dict[str, Any]], *, geom_key: str = "geom_geojson") -> List[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        geometry = payload.pop(geom_key, None)
        try:
            geometry_payload = json.loads(geometry) if geometry else None
        except json.JSONDecodeError:
            geometry_payload = None
        properties = _normalize(payload)
        features.append(
            {
                "type": "Feature",
                "geometry": geometry_payload,
                "properties": properties,
            }
        )
    return features


class NeighborhoodStatsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, neighborhood_code: str):
        """Return the latest snapshot for a neighborhood code."""

        code = (neighborhood_code or "").strip()
        if not code:
            raise ValidationError({"neighborhood_code": "Required"})

        year_param = request.query_params.get("year")
        year: Optional[int] = None
        if year_param:
            try:
                year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"year": "Must be an integer year."})

        snapshot = get_neighborhood_snapshot(code, year=year)
        if not snapshot:
            raise Http404("Neighborhood metrics not found.")

        return Response(_normalize(snapshot), status=status.HTTP_200_OK)


class FlavorSignalAiView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        limit_param = request.query_params.get("limit")
        limit = 3
        if limit_param:
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                pass
        limit = max(1, min(limit, 3))

        payload = fetch_flavor_signal_ai_messages(limit=limit)
        return Response(payload, status=status.HTTP_200_OK)


def _build_base_search_filters(params) -> Tuple[List[str], List[Any]]:
    """
    Construct WHERE clauses and parameter list for parcel search endpoints.
    """
    clauses: List[str] = ["UPPER(TRIM(COALESCE(mp.proptype, ''))) = 'R'"]
    args: List[Any] = []

    address = params.get("address")
    if address:
        clauses.append("mp.situs_address ILIKE %s")
        args.append(f"%{address}%")

    parcel_number = params.get("parcel_number")
    if parcel_number:
        clauses.append("mp.parcel_number = %s")
        args.append(parcel_number)

    min_value = params.get("min_value")
    if min_value:
        try:
            parsed = float(min_value)
        except (TypeError, ValueError):
            raise ValidationError({"min_value": "Must be a number."})
        clauses.append("mp.assessed_value >= %s")
        args.append(parsed)

    max_value = params.get("max_value")
    if max_value:
        try:
            parsed = float(max_value)
        except (TypeError, ValueError):
            raise ValidationError({"max_value": "Must be a number."})
        clauses.append("mp.assessed_value <= %s")
        args.append(parsed)

    district = params.get("district")
    if district:
        clauses.append("mp.city_district = %s")
        args.append(district)

    min_year = params.get("min_year")
    if min_year:
        try:
            parsed = int(min_year)
        except (TypeError, ValueError):
            raise ValidationError({"min_year": "Must be an integer year."})
        clauses.append("mp.year_built >= %s")
        args.append(parsed)

    max_year = params.get("max_year")
    if max_year:
        try:
            parsed = int(max_year)
        except (TypeError, ValueError):
            raise ValidationError({"max_year": "Must be an integer year."})
        clauses.append("mp.year_built <= %s")
        args.append(parsed)

    min_acres = params.get("min_acres")
    if min_acres:
        try:
            parsed = float(min_acres)
        except (TypeError, ValueError):
            raise ValidationError({"min_acres": "Must be a number."})
        clauses.append("mp.acres >= %s")
        args.append(parsed)

    max_acres = params.get("max_acres")
    if max_acres:
        try:
            parsed = float(max_acres)
        except (TypeError, ValueError):
            raise ValidationError({"max_acres": "Must be a number."})
        clauses.append("mp.acres <= %s")
        args.append(parsed)

    min_sale_price = params.get("min_sale_price")
    if min_sale_price:
        try:
            parsed = float(min_sale_price)
        except (TypeError, ValueError):
            raise ValidationError({"min_sale_price": "Must be a number."})
        clauses.append("(latest_sale.sale_price >= %s)")
        args.append(parsed)

    max_sale_price = params.get("max_sale_price")
    if max_sale_price:
        try:
            parsed = float(max_sale_price)
        except (TypeError, ValueError):
            raise ValidationError({"max_sale_price": "Must be a number."})
        clauses.append("(latest_sale.sale_price <= %s)")
        args.append(parsed)

    return clauses, args


class ParcelTaxDistrictAgenciesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        parcel_id = (request.query_params.get("parcel_id") or request.query_params.get("parcel_number") or "").strip()
        if not parcel_id:
            raise ValidationError({"parcel_id": "Required"})

        geometry = (
            ParcelGeometry.objects.filter(parcel__parcel_number=parcel_id)
            .only("centroid_geog", "latitude", "longitude", "centroid_2926", "geom_2926", "geom")
            .first()
        )
        if not geometry:
            raise Http404("Parcel geometry not found.")

        lon = None
        lat = None
        if geometry.centroid_geog:
            lon = geometry.centroid_geog.x
            lat = geometry.centroid_geog.y
        elif geometry.latitude is not None and geometry.longitude is not None:
            lat = geometry.latitude
            lon = geometry.longitude
        elif geometry.centroid_2926:
            centroid = geometry.centroid_2926.clone()
            centroid.transform(4326)
            lon = centroid.x
            lat = centroid.y
        elif geometry.geom_2926:
            centroid = geometry.geom_2926.centroid
            centroid.transform(4326)
            lon = centroid.x
            lat = centroid.y
        elif geometry.geom:
            centroid = geometry.geom.centroid
            centroid.transform(4326)
            lon = centroid.x
            lat = centroid.y

        if lat is None or lon is None:
            raise Http404("Parcel centroid not available.")

        boundary_year = _get_latest_sao_property_tax_year()
        try:
            boundary_rows = _fetch_sao_mcags_for_point(lat, lon, boundary_year)
        except Exception as exc:
            logger.exception("Failed to fetch SAO boundary data.")
            raise APIException("Unable to load SAO boundary data at this time.") from exc

        mcag_rows = []
        seen_mcags: Set[str] = set()
        for entry in boundary_rows:
            mcag = (entry.get("mcag") or "").strip()
            county_id = entry.get("countyId")
            if county_id not in (None, 29):
                continue
            if not mcag or mcag in seen_mcags:
                continue
            seen_mcags.add(mcag)
            mcag_rows.append(
                {
                    "mcag": mcag,
                    "gov_type_code": entry.get("govTypeCode"),
                    "county_id": county_id,
                }
            )

        snapshot_map: Dict[str, AgencyFinancialSnapshot] = {}
        if seen_mcags:
            snapshots = (
                AgencyFinancialSnapshot.objects.filter(mcag__in=seen_mcags)
                .order_by("mcag", "-year")
                .distinct("mcag")
                .only("mcag", "name", "year", "website", "gov_type_desc", "is_school", "dataset_source")
            )
            snapshot_map = {snapshot.mcag: snapshot for snapshot in snapshots}

        rows = []
        for row in mcag_rows:
            mcag = row["mcag"]
            snapshot = snapshot_map.get(mcag)
            if snapshot:
                row.update(
                    {
                        "snapshot_name": snapshot.name,
                        "snapshot_year": snapshot.year,
                        "snapshot_website": snapshot.website,
                        "snapshot_type": snapshot.gov_type_desc,
                        "snapshot_is_school": snapshot.is_school,
                        "snapshot_dataset": snapshot.dataset_source,
                    }
                )
            else:
                row.update(
                    {
                        "snapshot_name": None,
                        "snapshot_year": None,
                        "snapshot_website": None,
                        "snapshot_type": None,
                        "snapshot_is_school": None,
                        "snapshot_dataset": None,
                    }
                )
            rows.append(row)

        rows.sort(key=lambda record: record.get("snapshot_name") or record.get("mcag") or "")

        rows.append(
            {
                "mcag": "",
                "gov_type_code": "countywide",
                "snapshot_name": "Countywide fund",
                "snapshot_year": boundary_year,
                "snapshot_type": "Countywide services",
                "snapshot_dataset": "Shared county / state levies",
                "snapshot_website": None,
            }
        )

        payload = {
            "parcel_id": parcel_id,
            "boundary_year": boundary_year,
            "rows": rows,
        }
        return Response(_normalize(payload), status=status.HTTP_200_OK)


class ParcelTaxDistrictMembershipView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        parcel_id = (request.query_params.get("parcel_id") or request.query_params.get("parcel_number") or "").strip()
        if not parcel_id:
            raise ValidationError({"parcel_id": "Required"})

        year_param = request.query_params.get("tax_year") or request.query_params.get("year")
        target_year: Optional[int] = None
        if year_param:
            try:
                target_year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"tax_year": "Must be an integer year."})

        assessment_year = _resolve_assessment_year(target_year)
        if assessment_year is None:
            raise Http404("No tax district data available for this parcel.")

        master = (
            MasterParcel.objects.filter(parcel_number=parcel_id)
            .only("taxable_value", "assessed_value", "total_market_value")
            .first()
        )
        if not master:
            raise Http404("Parcel not found.")

        value_source = None
        taxable_value = None
        for source, raw_value in (
            ("taxable_value", master.taxable_value),
            ("assessed_value", master.assessed_value),
            ("total_market_value", master.total_market_value),
        ):
            if raw_value is None:
                continue
            try:
                taxable_value = float(raw_value)
            except (TypeError, ValueError):
                taxable_value = None
            if taxable_value is not None:
                value_source = source
                break

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (p.district_type, p.district_code)
                    p.district_type,
                    p.district_code,
                    COALESCE(
                        NULLIF(d.district_name, ''),
                        NULLIF(tl.district_name, ''),
                        CASE
                            WHEN p.district_type IS NOT NULL AND p.district_code IS NOT NULL THEN UPPER(p.district_type) || ' ' || p.district_code
                            WHEN p.district_type IS NOT NULL THEN UPPER(p.district_type)
                            WHEN p.district_code IS NOT NULL THEN p.district_code
                            ELSE 'District'
                        END
                    ) AS district_name,
                    d.county_name AS county_name,
                    dt.tdcode,
                    COALESCE(tl.district_name, '') AS levy_name,
                    tl.levy_rate AS levy_rate,
                    alm.mcag,
                    alm.agency_name,
                    alm.agency_type,
                    alm.is_primary,
                    afs.name AS snapshot_name,
                    afs.year AS snapshot_year,
                    afs.website AS snapshot_website,
                    afs.dataset_source AS snapshot_dataset,
                    afs.gov_type_desc AS snapshot_type
                FROM parcel_tax_district p
                LEFT JOIN reference_tax_district d
                    ON d.district_type = p.district_type
                   AND d.district_code = p.district_code
                LEFT JOIN district_tdcode dt
                    ON dt.district_type = p.district_type
                   AND dt.district_code = p.district_code
                   AND dt.assessment_year = %s
                LEFT JOIN taxing_district_levy tl
                    ON tl.tdcode = dt.tdcode
                   AND tl.assessment_year = %s
                LEFT JOIN agency_levy_map alm
                    ON alm.tdcode = dt.tdcode
                   AND alm.is_primary = true
                LEFT JOIN LATERAL (
                    SELECT name, year, website, dataset_source, gov_type_desc
                    FROM openskagit_agencyfinancialsnapshot
                    WHERE mcag = alm.mcag
                    ORDER BY year DESC
                    LIMIT 1
                ) afs ON true
                WHERE p.parcel_id = %s
                ORDER BY p.district_type, p.district_code
                """,
                [assessment_year, assessment_year, parcel_id],
            )
            rows = _dictfetchall(cursor)

        unique_rows: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str]] = set()
        for row in rows:
            dtype = (row.get("district_type") or "").strip().lower()
            dcode = str(row.get("district_code") or "").strip()
            key = (dtype, dcode)
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
        rows = unique_rows

        if not rows:
            raise Http404("No parcel tax district coverage could be determined.")

        total_levy_rate = 0.0
        for row in rows:
            levy_rate = row.get("levy_rate")
            if levy_rate is None:
                continue
            try:
                total_levy_rate += float(levy_rate)
            except (TypeError, ValueError):
                continue

        normalized_total = 0.0
        for row in rows:
            levy_rate = row.get("levy_rate")
            levy_rate_value = None
            if levy_rate is not None:
                try:
                    levy_rate_value = float(levy_rate)
                except (TypeError, ValueError):
                    levy_rate_value = None
            allocated_tax = None
            if levy_rate_value is not None and taxable_value is not None:
                allocated_tax = (taxable_value / 1000.0) * levy_rate_value
                normalized_total += allocated_tax
            levy_share = (levy_rate_value / total_levy_rate) if levy_rate_value and total_levy_rate else None
            row.update(
                {
                    "levy_rate": levy_rate_value,
                    "allocated_tax": allocated_tax,
                    "levy_share": levy_share,
                }
            )

        has_countywide = any((row.get("district_type") or "").strip().lower() == "countywide" for row in rows)
        if not has_countywide:
            rows.append(
                {
                    "district_type": "countywide",
                    "district_code": "",
                    "district_name": "Countywide fund",
                    "county_name": "Skagit County",
                    "tdcode": "290000000",
                    "levy_name": "Countywide services",
                    "allocated_tax": None,
                    "levy_share": None,
                    "levy_rate": None,
                    "mcag": "",
                    "agency_name": "Countywide fund",
                    "agency_type": "fund",
                    "snapshot_name": "Countywide fund",
                    "snapshot_year": assessment_year,
                    "snapshot_type": "Countywide services",
                    "snapshot_dataset": "Shared county / state levies",
                    "snapshot_website": None,
                }
            )

        payload = {
            "parcel_id": parcel_id,
            "tax_year": assessment_year,
            "assessment_year": assessment_year,
            "total_allocated": normalized_total if taxable_value is not None else None,
            "value_used": taxable_value,
            "value_source": value_source,
            "source": "parcel_tax_district",
            "rows": rows,
        }
        return Response(_normalize(payload), status=status.HTTP_200_OK)


class AgencyExpenseBreakdownView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        mcag = (request.query_params.get("mcag") or "").strip()
        if not mcag:
            raise ValidationError({"mcag": "Required"})

        year_param = request.query_params.get("year")
        target_year: Optional[int] = None
        if year_param:
            try:
                target_year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"year": "Must be an integer year."})

        qs = AgencyFinancialSnapshot.objects.filter(mcag=mcag)
        if target_year:
            qs = qs.filter(year=target_year)
        snapshot = qs.order_by("-year").first()
        if not snapshot:
            raise Http404("Agency financials not found.")

        year_used = snapshot.year

        categories = []
        for entry in snapshot.expenditures or []:
            values = entry.get("values") or {}
            amount = None
            if target_year is not None:
                amount = values.get(str(target_year))
            if amount is None:
                amount = values.get(str(year_used))
            if amount is None and values:
                try:
                    latest_key = max(values.keys(), key=lambda k: int(k))
                    amount = values.get(latest_key)
                except Exception:
                    amount = None
            if amount is None:
                continue
            label = entry.get("label") or entry.get("code") or "Unlabeled"
            categories.append(
                {
                    "label": label,
                    "amount": amount,
                    "code": entry.get("code"),
                }
            )

        categories.sort(key=lambda c: c["amount"] or 0, reverse=True)
        total = sum((c["amount"] or 0) for c in categories)

        payload = {
            "mcag": mcag,
            "agency_name": snapshot.name,
            "year": year_used,
            "total_expenditures": total,
            "categories": categories,
        }

        return Response(_normalize(payload), status=status.HTTP_200_OK)


def _build_snapshot_label_map(snapshot: AgencyFinancialSnapshot) -> Dict[str, str]:
    label_map: Dict[str, str] = {}
    for key in ("revenues", "expenditures"):
        payload = (snapshot.raw_payloads or {}).get(key) or {}
        for entry in payload.get("value", []) or []:
            basic_id = entry.get("basicAccountId") or entry.get("id")
            if basic_id is None:
                continue
            label = (
                entry.get("label")
                or entry.get("accountTitle")
                or entry.get("accountName")
                or entry.get("name")
                or entry.get("description")
            )
            if label:
                label_map[str(basic_id)] = label
    return label_map


class AgencyFinancialBreakdownView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        mcag = (request.query_params.get("mcag") or "").strip()
        if not mcag:
            raise ValidationError({"mcag": "Required"})

        year_param = request.query_params.get("year")
        target_year: Optional[int] = None
        if year_param:
            try:
                target_year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"year": "Must be an integer year."})

        qs = AgencyFinancialSnapshot.objects.filter(mcag=mcag)
        if target_year:
            qs = qs.filter(year=target_year)
        snapshot = qs.order_by("-year").first()
        if not snapshot:
            raise Http404("Agency financials not found.")

        year_used = snapshot.year

        def build_categories(entries: Optional[List[Dict[str, Any]]]):
            categories = []
            for entry in entries or []:
                values = entry.get("values") or {}
                amount = None
                if target_year is not None:
                    amount = values.get(str(target_year))
                if amount is None:
                    amount = values.get(str(year_used))
                if amount is None and values:
                    try:
                        latest_key = max(values.keys(), key=lambda k: int(k))
                        amount = values.get(latest_key)
                    except Exception:
                        amount = None
                if amount is None:
                    continue
                label = entry.get("label") or entry.get("code") or "Unlabeled"
                categories.append(
                    {
                        "label": label,
                        "amount": amount,
                        "code": entry.get("code"),
                    }
                )

            categories.sort(key=lambda c: c["amount"] or 0, reverse=True)
            total = sum((c["amount"] or 0) for c in categories)
            return categories, total

        revenues, total_revenues = build_categories(snapshot.revenues)
        expenditures, total_expenditures = build_categories(snapshot.expenditures)

        label_map = _build_snapshot_label_map(snapshot)
        for row in revenues + expenditures:
            if not row.get("label"):
                label = label_map.get(str(row.get("code")))
                if label:
                    row["label"] = label

        payload = {
            "mcag": mcag,
            "agency_name": snapshot.name,
            "year": year_used,
            "total_revenues": total_revenues,
            "total_expenditures": total_expenditures,
            "revenues": revenues,
            "expenditures": expenditures,
        }

        return Response(_normalize(payload), status=status.HTTP_200_OK)


def _resolve_assessment_year(requested_year: Optional[int]) -> Optional[int]:
    latest_assessment_year = None
    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(assessment_year) FROM district_tdcode")
        row = cursor.fetchone()
        latest_assessment_year = row[0] if row else None

    if latest_assessment_year is None:
        latest_assessment_year = (
            TaxingDistrictLevy.objects.order_by("-assessment_year")
            .values_list("assessment_year", flat=True)
            .first()
        )

    if requested_year is None:
        return latest_assessment_year

    has_assessment_year = False
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM district_tdcode WHERE assessment_year = %s LIMIT 1",
            [requested_year],
        )
        has_assessment_year = cursor.fetchone() is not None

    if latest_assessment_year and (not has_assessment_year or requested_year > latest_assessment_year):
        return latest_assessment_year

    return requested_year


class ParcelTaxLevyEstimateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        parcel_id = (request.query_params.get("parcel_id") or request.query_params.get("parcel_number") or "").strip()
        if not parcel_id:
            raise ValidationError({"parcel_id": "Required"})

        year_param = request.query_params.get("tax_year") or request.query_params.get("year")
        requested_year: Optional[int] = None
        if year_param:
            try:
                requested_year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"tax_year": "Must be an integer."})

        assessment_year = _resolve_assessment_year(requested_year)
        if assessment_year is None:
            raise Http404("No levy data available.")

        master = (
            MasterParcel.objects.filter(parcel_number=parcel_id)
            .only("taxable_value", "assessed_value", "total_market_value")
            .first()
        )
        if not master:
            raise Http404("Parcel not found.")

        value_source = None
        taxable_value = None
        for source, raw_value in (
            ("taxable_value", master.taxable_value),
            ("assessed_value", master.assessed_value),
            ("total_market_value", master.total_market_value),
        ):
            if raw_value is None:
                continue
            try:
                taxable_value = float(raw_value)
            except (TypeError, ValueError):
                taxable_value = None
            if taxable_value is not None:
                value_source = source
                break

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (p.district_type, p.district_code)
                    p.district_type,
                    p.district_code,
                    COALESCE(
                        NULLIF(d.district_name, ''),
                        NULLIF(tl.district_name, ''),
                        CASE
                            WHEN p.district_type IS NOT NULL AND p.district_code IS NOT NULL THEN UPPER(p.district_type) || ' ' || p.district_code
                            WHEN p.district_type IS NOT NULL THEN UPPER(p.district_type)
                            WHEN p.district_code IS NOT NULL THEN p.district_code
                            ELSE 'District'
                        END
                    ) AS district_name,
                    dt.tdcode,
                    tl.levy_rate
                FROM parcel_tax_district p
                LEFT JOIN reference_tax_district d
                    ON d.district_type = p.district_type
                   AND d.district_code = p.district_code
                LEFT JOIN district_tdcode dt
                    ON dt.district_type = p.district_type
                   AND dt.district_code = p.district_code
                   AND dt.assessment_year = %s
                LEFT JOIN taxing_district_levy tl
                    ON tl.tdcode = dt.tdcode
                   AND tl.assessment_year = %s
                WHERE p.parcel_id = %s
                ORDER BY p.district_type, p.district_code
                """,
                [assessment_year, assessment_year, parcel_id],
            )
            rows = _dictfetchall(cursor)

        if not rows:
            raise Http404("No tax district data available for this parcel.")

        total_levy_rate = 0.0
        for row in rows:
            levy_rate = row.get("levy_rate")
            if levy_rate is None:
                continue
            try:
                total_levy_rate += float(levy_rate)
            except (TypeError, ValueError):
                continue

        total_estimated = 0.0
        for row in rows:
            district_name = row.get("district_name") or "District"
            levy_rate = row.get("levy_rate")
            levy_rate_value = None
            if levy_rate is not None:
                try:
                    levy_rate_value = float(levy_rate)
                except (TypeError, ValueError):
                    levy_rate_value = None
            amount = None
            if levy_rate_value is not None and taxable_value is not None:
                amount = (taxable_value / 1000.0) * levy_rate_value
                total_estimated += amount
            share = (levy_rate_value / total_levy_rate) if levy_rate_value and total_levy_rate else None
            row.update(
                {
                    "tax_district": district_name,
                    "rate": levy_rate_value,
                    "amount": amount,
                    "share": share,
                    "category": _classify_tax_district(district_name),
                }
            )

        rows.sort(key=lambda r: r.get("amount") or 0, reverse=True)

        payload = {
            "parcel_id": parcel_id,
            "tax_year": assessment_year,
            "assessment_year": assessment_year,
            "total_amount": total_estimated if taxable_value is not None else None,
            "total_levy_rate": total_levy_rate if total_levy_rate else None,
            "value_used": taxable_value,
            "value_source": value_source,
            "rows": rows,
            "source": "levy_estimate",
        }

        return Response(_normalize(payload), status=status.HTTP_200_OK)


def _tax_value_for_year(rows: Any, target_year: int) -> Optional[Tuple[float, float]]:
    rows = _coerce_history_rows(rows)
    if not rows:
        return None
    for row in rows:
        year = _extract_history_year(row)
        if year != target_year:
            continue
        tax = _extract_history_tax(row)
        value = _extract_history_value(row)
        if tax is None or value is None:
            continue
        if value <= 0 or tax <= 0:
            continue
        return float(tax), float(value)
    return None


class ParcelTaxFairnessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        parcel_id = (request.query_params.get("parcel_id") or request.query_params.get("parcel_number") or "").strip()
        if not parcel_id:
            raise ValidationError({"parcel_id": "Required"})

        tax_year_param = request.query_params.get("tax_year") or request.query_params.get("year")
        requested_year: Optional[int] = None
        if tax_year_param:
            try:
                requested_year = int(tax_year_param)
            except (TypeError, ValueError):
                raise ValidationError({"tax_year": "Must be an integer."})

        history = (
            ParcelHistory.objects.filter(parcel_number=parcel_id)
            .only("rows")
            .first()
        )
        if not history:
            raise Http404("Parcel history not available.")

        allowed_years = {2025, 2026}
        candidate_year = None
        rows = _coerce_history_rows(history.rows)
        row_years = {year for row in rows if (year := _extract_history_year(row)) in allowed_years}
        if requested_year in allowed_years and requested_year in row_years:
            candidate_year = requested_year
        elif row_years:
            candidate_year = max(row_years)

        if candidate_year is None:
            raise Http404("No 2025/2026 parcel history available.")

        subject_pair = _tax_value_for_year(history.rows, candidate_year)
        if not subject_pair:
            raise Http404("Parcel tax/value not available for 2025/2026.")
        subject_tax, subject_value = subject_pair
        subject_etr = subject_tax / subject_value if subject_value else None
        if subject_etr is None:
            raise Http404("Parcel ETR not available for 2025/2026.")

        master = (
            MasterParcel.objects.filter(parcel_number=parcel_id)
            .only("parcel_number", "hood_code", "hood_description")
            .first()
        )
        hood_code = master.hood_code if master else None
        if not hood_code:
            raise Http404("Parcel neighborhood not found.")
        hood_description = master.hood_description or ""

        peer_parcels = MasterParcel.objects.filter(hood_code=hood_code).values_list("parcel_number", flat=True)
        peer_qs = ParcelHistory.objects.filter(parcel_number__in=peer_parcels).only("parcel_number", "rows")
        etrs: List[float] = []
        for record in peer_qs.iterator():
            pair = _tax_value_for_year(record.rows, candidate_year)
            if not pair:
                continue
            tax_value, assessed_value = pair
            etr = tax_value / assessed_value if assessed_value else None
            if etr is None or etr <= 0:
                continue
            etrs.append(etr)

        if not etrs:
            raise Http404("No peer ETR data available for 2025/2026.")

        sorted_etrs = sorted(etrs)
        count = len(sorted_etrs)
        mid = count // 2
        if count % 2:
            median_etr = sorted_etrs[mid]
        else:
            median_etr = (sorted_etrs[mid - 1] + sorted_etrs[mid]) / 2.0
        mean_etr = sum(sorted_etrs) / count
        cod = None
        prd = None
        if median_etr:
            cod = (sum(abs(etr - median_etr) for etr in sorted_etrs) / (count * median_etr)) * 100
            prd = mean_etr / median_etr

        percentile = sum(1 for etr in sorted_etrs if etr <= subject_etr) / count

        payload = {
            "parcel_id": parcel_id,
            "tax_year": candidate_year,
            "hood_code": hood_code,
            "hood_description": hood_description,
            "sample_count": count,
            "subject_etr": subject_etr,
            "hood_min": sorted_etrs[0],
            "hood_max": sorted_etrs[-1],
            "hood_median": median_etr,
            "hood_mean": mean_etr,
            "cod": cod,
            "prd": prd,
            "neighbor_count": count,
            "subject_etr_percentile": percentile,
            "subject_etr_percentile_rank": round(percentile * 100, 1),
            "source": "parcel_history",
        }

        return Response(_normalize(payload), status=status.HTTP_200_OK)


REFERENCE_INFLATION_RATES = {
    2018: 0.020,
    2019: 0.018,
    2020: 0.014,
    2021: 0.071,
    2022: 0.065,
    2023: 0.032,
    2024: 0.034,
    2025: 0.032,
}
DEFAULT_INFLATION_RATE = 0.03


def _average_inflation_rate(start_year: int, end_year: int) -> float:
    if end_year <= start_year:
        return DEFAULT_INFLATION_RATE
    span = end_year - start_year
    factors = [
        1 + REFERENCE_INFLATION_RATES.get(year, DEFAULT_INFLATION_RATE)
        for year in range(start_year + 1, end_year + 1)
    ]
    if not factors:
        return DEFAULT_INFLATION_RATE
    total = 1.0
    for factor in factors:
        total *= factor
    return float(total ** (1 / span) - 1)


class ParcelTaxStoryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        parcel_id = (request.query_params.get("parcel_id") or request.query_params.get("parcel_number") or "").strip()
        if not parcel_id:
            raise ValidationError({"parcel_id": "Required"})

        master = (
            MasterParcel.objects.filter(parcel_number=parcel_id)
            .only("total_market_value")
            .first()
        )

        record = ParcelHistory.objects.only("rows").filter(parcel_number=parcel_id).first()
        rows = _coerce_history_rows(record.rows) if record else None
        if not rows:
            raise Http404("Parcel history not available.")

        tax_history: List[Dict[str, Any]] = []
        for row in rows:
            year = _extract_history_year(row)
            tax_value = _extract_history_tax(row)
            if year is None or tax_value is None:
                continue
            tax_history.append(
                {
                    "year": year,
                    "tax": tax_value,
                    "value": _extract_history_value(row),
                }
            )
        tax_history.sort(key=lambda entry: entry["year"])

        cumulative_taxes = sum(entry["tax"] for entry in tax_history)
        tax_trend_cagr = None
        inflation_avg = None
        tax_vs_inflation = None
        history_years = None
        if len(tax_history) >= 2:
            first = tax_history[0]
            last = tax_history[-1]
            span = last["year"] - first["year"]
            history_years = {"start": first["year"], "end": last["year"], "span": span}
            if span > 0 and first["tax"] > 0 and last["tax"] > 0:
                tax_trend_cagr = (last["tax"] / first["tax"]) ** (1 / span) - 1
                inflation_avg = _average_inflation_rate(first["year"], last["year"])
                tax_vs_inflation = tax_trend_cagr - inflation_avg

        total_market_value = None
        if tax_history:
            total_market_value = tax_history[-1].get("value")
        if total_market_value is None and master and master.total_market_value:
            try:
                total_market_value = float(master.total_market_value)
            except (TypeError, ValueError):
                total_market_value = None

        value_history_points = [
            {
                "year": entry["year"],
                "value": entry["value"],
            }
            for entry in tax_history
            if entry.get("year") is not None and entry.get("value") is not None
        ]
        value_history_points.sort(key=lambda item: item["year"])
        value_history_5y = value_history_points[-5:]

        annual_tax_points = []
        cumulative_total = 0.0
        for entry in tax_history:
            year = entry.get("year")
            tax_value = entry.get("tax")
            if year is None or tax_value is None:
                continue
            cumulative_total += tax_value
            annual_tax_points.append(
                {
                    "year": year,
                    "annual_tax": tax_value,
                    "cumulative": cumulative_total,
                }
            )

        payload = {
            "parcel_id": parcel_id,
            "total_market_value": total_market_value,
            "cumulative_taxes_paid": cumulative_taxes,
            "tax_trend_cagr": tax_trend_cagr,
            "inflation_avg": inflation_avg,
            "tax_vs_inflation": tax_vs_inflation,
            "history_years": history_years,
            "value_history_5y": value_history_5y,
            "annual_tax_points": annual_tax_points,
            "source": "parcel_history_rows",
        }

        return Response(_normalize(payload), status=status.HTTP_200_OK)


class ParcelTaxAiSummaryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        parcel_id = (request.query_params.get("parcel_id") or request.query_params.get("parcel_number") or "").strip()
        if not parcel_id:
            raise ValidationError({"parcel_id": "Required"})

        payload = get_cached_parcel_tax_ai_summary(parcel_id)
        if payload:
            if payload.get("status") == "failed":
                failed_at = payload.get("failed_at_ts")
                if failed_at and (time.time() - float(failed_at)) > TAX_AI_FAILURE_RETRY_SECONDS:
                    enqueue_parcel_tax_ai_summary(parcel_id)
                    return Response({"parcel_id": parcel_id, "status": "pending"}, status=status.HTTP_202_ACCEPTED)
            return Response(payload, status=status.HTTP_200_OK)

        history = (
            ParcelHistory.objects.filter(parcel_number=parcel_id)
            .only("rows")
            .first()
        )
        rows = _coerce_history_rows(history.rows) if history else None
        if not rows:
            raise Http404("Parcel history not available.")

        enqueue_parcel_tax_ai_summary(parcel_id)
        return Response({"parcel_id": parcel_id, "status": "pending"}, status=status.HTTP_202_ACCEPTED)


class CountyEtrView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        year_param = request.query_params.get("year")
        if not year_param:
            raise ValidationError({"year": "Required"})
        try:
            year = int(year_param)
        except (TypeError, ValueError):
            raise ValidationError({"year": "Must be an integer."})

        insights = county_etr_insights(year)
        if not insights:
            raise Http404("County ETR data unavailable.")

        return Response(_normalize(insights), status=status.HTTP_200_OK)


def _classify_tax_district(name: str) -> str:
    upper = name.upper()
    if "STATE" in upper or "COUNTY" in upper or "CONSERVATION" in upper or "ROAD" in upper:
        return "fund"
    if "SCHOOL" in upper:
        return "school"
    if "HOSPITAL" in upper:
        return "hospital"
    if "PORT" in upper:
        return "port"
    if "FIRE" in upper:
        return "fire"
    if "EMS" in upper or "MEDIC" in upper:
        return "ems"
    if "PARK" in upper or "RECREATION" in upper:
        return "park"
    if "CEMETERY" in upper:
        return "cemetery"
    if "CITY" in upper or "TOWN" in upper:
        return "city"
    return "district"


class NeighborhoodTaxMapView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        hood_code = (request.query_params.get("hood_code") or "").strip()
        with connection.cursor() as cursor:
            if hood_code:
                cursor.execute(
                    """
                    SELECT DISTINCT tax_year
                    FROM hood_tax_totals
                    WHERE hood_code = %s
                    ORDER BY tax_year DESC
                    """,
                    [hood_code],
                )
            else:
                cursor.execute("SELECT DISTINCT tax_year FROM hood_tax_totals ORDER BY tax_year DESC")
            available_years = [row[0] for row in cursor.fetchall()]

        if not available_years:
            raise Http404("No neighborhood tax totals available.")

        year_param = request.query_params.get("year")
        if year_param in (None, ""):
            year = available_years[0]
        else:
            try:
                year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"year": "Must be an integer year."})

        clauses = ["h.tax_year = %s"]
        params: List[Any] = [year]
        if hood_code:
            clauses.append("h.hood_code = %s")
            params.append(hood_code)
        where_clause = "WHERE " + " AND ".join(clauses)

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    h.hood_code,
                    h.tax_year,
                    h.total_tax,
                    h.total_market_value,
                    h.total_taxable_value,
                    h.parcel_count,
                    COALESCE(ng.name, h.hood_code) AS neighborhood_name,
                    ST_AsGeoJSON(ng.geom_4326, 6) AS geom_geojson
                FROM hood_tax_totals h
                LEFT JOIN public.openskagit_neighborhoodgeom ng
                  ON ng.code = h.hood_code
                {where_clause}
                ORDER BY h.total_tax DESC NULLS LAST
                """,
                params,
            )
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]

        features: List[Dict[str, Any]] = []
        for row in rows:
            geometry = row.pop("geom_geojson")
            try:
                geometry_payload = json.loads(geometry) if geometry else None
            except json.JSONDecodeError:
                geometry_payload = None
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry_payload,
                    "properties": row,
                }
            )

        return Response(
            {
                "type": "FeatureCollection",
                "year": year,
                "available_years": available_years,
                "features": features,
            },
            status=status.HTTP_200_OK,
        )


def _coalesce_list(value: Optional[Iterable[Any]]) -> List[Any]:
    if value is None:
        return []
    return list(value)


PARCEL_DETAIL_SQL = """
    SELECT
        mp.parcel_number,
        mp.situs_address AS address,
        mp.assessed_value,
        mp.total_market_value,
        mp.taxable_value,
        mp.number_of_bedrooms AS bedrooms,
        mp.total_baths AS bathrooms,
        mp.final_living_area AS living_area,
        mp.year_built,
        mp.eff_year_built,
        mp.acres,
        mp.city_district,
        mp.school_district,
        mp.fire_district,
        COALESCE(
            pg.latitude,
            ST_Y(pg.centroid_geog),
            ST_Y(ST_Transform(ST_Centroid(pg.geom), 4326))
        ) AS latitude,
        COALESCE(
            pg.longitude,
            ST_X(pg.centroid_geog),
            ST_X(ST_Transform(ST_Centroid(pg.geom), 4326))
        ) AS longitude,
        COALESCE(land.land_segments, '[]'::json) AS land_segments,
        COALESCE(improvements.improvements, '[]'::json) AS improvements,
        COALESCE(sales.sales_array, '[]'::json) AS sales
    FROM master_parcel mp
    LEFT JOIN parcel_geometry pg ON pg.parcel_id = mp.parcel_number
    LEFT JOIN LATERAL (
        SELECT json_agg(
            json_strip_nulls(
                json_build_object(
                    'property_value_year', lf.property_value_year,
                    'land_type', lf.land_type,
                    'size_acres', lf.size_acres,
                    'size_square_feet', lf.size_square_feet,
                    'market_value', lf.market_value,
                    'market_unit_price', lf.market_unit_price
                )
            )
            ORDER BY lf.property_value_year DESC NULLS LAST,
                     lf.land_segment_id,
                     lf.market_value DESC NULLS LAST
        ) AS land_segments
        FROM (
            SELECT *
                FROM (
                    SELECT l.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY l.land_segment_id,
                                            l.property_value_year,
                                            l.land_type
                           ORDER BY l.property_value_year DESC NULLS LAST,
                                    l.market_value DESC NULLS LAST,
                                    l.land_segment_id
                       ) AS rn
                FROM land l
                WHERE l.parcel_number = mp.parcel_number
            ) ranked_land
            WHERE rn = 1
        ) lf
    ) land ON TRUE
    LEFT JOIN LATERAL (
        SELECT json_agg(
            json_strip_nulls(
                json_build_object(
                    'improvement_id', improvement_filtered.improvement_id,
                    'description', improvement_filtered.description,
                    'building_style', improvement_filtered.building_style,
                    'condition_code', improvement_filtered.condition_code,
                    'improvement_value', improvement_filtered.improvement_value,
                    'total_living_area', improvement_filtered.total_living_area,
                    'actual_year_built', improvement_filtered.actual_year_built,
                    'effective_year_built', improvement_filtered.effective_year_built
                )
            )
            ORDER BY improvement_filtered.improvement_id,
                     improvement_filtered.effective_year_built DESC NULLS LAST,
                     improvement_filtered.actual_year_built DESC NULLS LAST
        ) AS improvements
        FROM (
            SELECT *
            FROM (
                SELECT i.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY i.improvement_id
                           ORDER BY
                               i.effective_year_built DESC NULLS LAST,
                               i.actual_year_built DESC NULLS LAST
                       ) AS rn
                FROM improvements i
                WHERE i.parcel_number = mp.parcel_number
            ) ranked_improvements
            WHERE rn = 1
        ) improvement_filtered
    ) improvements ON TRUE
    LEFT JOIN LATERAL (
        SELECT json_agg(
            json_strip_nulls(
                json_build_object(
                    'sale_price', sales_filtered.sale_price,
                    'sale_date', sales_filtered.sale_date,
                    'sale_type', sales_filtered.sale_type,
                    'deed_type', sales_filtered.deed_type,
                    'recording_number', sales_filtered.recording_number
                )
            )
            ORDER BY sales_filtered.sale_date DESC NULLS LAST,
                     sales_filtered.sale_price DESC NULLS LAST
        ) AS sales_array
        FROM (
            SELECT *
            FROM (
                SELECT s.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY s.sale_price,
                                        s.sale_date,
                                        s.recording_number
                                ORDER BY s.sale_id DESC NULLS LAST
                       ) AS rn
                FROM sales s
                WHERE s.parcel_number = mp.parcel_number
            ) ranked_sales
            WHERE rn = 1
        ) sales_filtered
    ) sales ON TRUE
    WHERE mp.parcel_number = %s
      AND UPPER(TRIM(COALESCE(mp.proptype, ''))) = 'R'
"""


class ParcelDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, parcel_number: str) -> Response:
        with connection.cursor() as cursor:
            cursor.execute(PARCEL_DETAIL_SQL, [parcel_number])
            record = _dictfetchone(cursor)

        if not record:
            raise Http404("Parcel not found.")

        record = {key: _normalize(value) for key, value in record.items()}
        sales = _coalesce_list(record.pop("sales"))
        latest_sale = sales[0] if sales else None

        land_segments = _coalesce_list(record.get("land_segments"))
        improvements = _coalesce_list(record.get("improvements"))

        land_total_acres = sum(
            segment.get("size_acres") or 0 for segment in land_segments if isinstance(segment, dict)
        ) or record.get("acres")
        land_total_market_value = sum(
            segment.get("market_value") or 0 for segment in land_segments if isinstance(segment, dict)
        ) or record.get("total_market_value")

        valid_sales = [
            sale for sale in sales if isinstance(sale, dict) and sale.get("sale_price") and sale.get("sale_price", 0) > 0
        ]
        recent_valid_sales = valid_sales[:5]

        structure = {
            "bedrooms": record.get("bedrooms"),
            "bathrooms": record.get("bathrooms"),
            "living_area_sqft": record.get("living_area"),
            "year_built": record.get("year_built"),
            "effective_year_built": record.get("eff_year_built"),
        }

        valuation = {
            "assessed": record.get("assessed_value"),
            "market": record.get("total_market_value"),
            "taxable": record.get("taxable_value"),
        }

        payload = {
            "parcel_number": record.get("parcel_number"),
            "address": record.get("address"),
            "valuation": valuation,
            "structure": structure,
            "districts": {
                "city": record.get("city_district"),
                "school": record.get("school_district"),
                "fire": record.get("fire_district"),
            },
            "location": {
                "latitude": record.get("latitude"),
                "longitude": record.get("longitude"),
                "acres": record.get("acres"),
            },
            "land": {
                "total_acres": land_total_acres,
                "total_market_value": land_total_market_value,
                "segments": land_segments,
            },
            "improvements": improvements,
            "sales": {
                "latest": latest_sale,
                "recent_valid": recent_valid_sales,
                "total_records": len(sales),
            },
        }
        return Response(payload)


class SalesListView(APIView):
    permission_classes = [AllowAny]

    DEFAULT_LIMIT = 25
    MAX_LIMIT = 100
    SORT_FIELDS = {
        "recent": ("s.sale_date", "DESC"),
        "sale_price": ("s.sale_price", "DESC"),
        "neighborhood": ("mp.hood_code", "ASC"),
        "assessed_value": ("mp.assessed_value", "DESC"),
        "market_value": ("mp.total_market_value", "DESC"),
        "acres": ("mp.acres", "DESC"),
        "year_built": ("mp.year_built", "DESC"),
    }

    def get(self, request) -> Response:
        params = request.query_params
        limit = _parse_positive_int(params.get("limit"), self.DEFAULT_LIMIT, max_value=self.MAX_LIMIT)

        sort_key = params.get("sort", "recent")
        if sort_key not in self.SORT_FIELDS:
            allowed = ", ".join(self.SORT_FIELDS)
            raise ValidationError({"sort": f"Unsupported sort '{sort_key}'. Allowed values: {allowed}."})

        base_column, default_direction = self.SORT_FIELDS[sort_key]
        direction_param = params.get("direction")
        if direction_param:
            direction_upper = direction_param.upper()
            if direction_upper not in {"ASC", "DESC"}:
                raise ValidationError({"direction": "Must be 'asc' or 'desc'."})
            order_direction = direction_upper
        else:
            order_direction = default_direction

        clauses = [
            "LOWER(TRIM(s.sale_type)) = 'valid sale'",
            "UPPER(TRIM(COALESCE(mp.proptype, ''))) = 'R'",
        ]
        args: List[Any] = []

        neighborhood = params.get("neighborhood")
        if neighborhood:
            clauses.append("mp.hood_code = %s")
            args.append(neighborhood)

        city = params.get("city")
        if city:
            clauses.append("mp.city_district = %s")
            args.append(city)

        parcel_number = params.get("parcel_number")
        if parcel_number:
            clauses.append("s.parcel_number = %s")
            args.append(parcel_number)

        min_price = params.get("min_sale_price")
        if min_price:
            try:
                parsed = float(min_price)
            except (TypeError, ValueError):
                raise ValidationError({"min_sale_price": "Must be numeric."})
            clauses.append("s.sale_price >= %s")
            args.append(parsed)

        max_price = params.get("max_sale_price")
        if max_price:
            try:
                parsed = float(max_price)
            except (TypeError, ValueError):
                raise ValidationError({"max_sale_price": "Must be numeric."})
            clauses.append("s.sale_price <= %s")
            args.append(parsed)

        start_date = _parse_iso_datetime(params.get("start_date"), "start_date")
        if start_date:
            clauses.append("s.sale_date >= %s")
            args.append(start_date)

        end_date = _parse_iso_datetime(params.get("end_date"), "end_date")
        if end_date:
            clauses.append("s.sale_date <= %s")
            args.append(end_date)

        land_use = params.get("land_use_code")
        if land_use:
            clauses.append("mp.land_use_code = %s")
            args.append(land_use)

        # Optional property_type will only further restrict results.
        property_type = params.get("property_type")
        if property_type:
            clauses.append("UPPER(TRIM(COALESCE(mp.proptype, ''))) = UPPER(TRIM(%s))")
            args.append(property_type)

        min_acres = params.get("min_acres")
        if min_acres:
            try:
                parsed = float(min_acres)
            except (TypeError, ValueError):
                raise ValidationError({"min_acres": "Must be numeric."})
            clauses.append("mp.acres >= %s")
            args.append(parsed)

        max_acres = params.get("max_acres")
        if max_acres:
            try:
                parsed = float(max_acres)
            except (TypeError, ValueError):
                raise ValidationError({"max_acres": "Must be numeric."})
            clauses.append("mp.acres <= %s")
            args.append(parsed)

        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        count_sql = f"""
            SELECT COUNT(*)
            FROM sales s
            JOIN master_parcel mp ON mp.parcel_number = s.parcel_number
            {where_clause}
        """

        data_sql = f"""
            SELECT
                s.sale_id,
                s.parcel_number,
                s.account_number,
                s.seller_name,
                s.buyer_name,
                s.sale_price,
                s.sale_date,
                s.sale_type,
                s.recording_number,
                s.deed_type,
                s.deed_date,
                s.revaluation_area,
                s.excise_number,
                mp.situs_address AS address,
                mp.hood_code AS neighborhood_code,
                mp.land_use_code,
                mp.proptype AS property_type,
                mp.city_district,
                mp.school_district,
                mp.fire_district,
                mp.assessed_value,
                mp.total_market_value,
                mp.taxable_value,
                mp.acres,
                mp.year_built,
                mp.eff_year_built,
                mp.number_of_bedrooms AS bedrooms,
                mp.total_baths AS bathrooms,
                COALESCE(mp.final_living_area, mp.total_living_area, mp.living_area) AS living_area,
                COALESCE(land.land_segments, '[]'::json) AS land_segments,
                COALESCE(improvements.improvements, '[]'::json) AS improvements
            FROM sales s
            JOIN master_parcel mp ON mp.parcel_number = s.parcel_number
            LEFT JOIN LATERAL (
                SELECT json_agg(
                    json_strip_nulls(
                        json_build_object(
                            'property_value_year', lf.property_value_year,
                            'land_type', lf.land_type,
                            'size_acres', lf.size_acres,
                            'size_square_feet', lf.size_square_feet,
                            'market_value', lf.market_value
                        )
                    )
                    ORDER BY lf.property_value_year DESC NULLS LAST,
                             lf.land_segment_id,
                             lf.market_value DESC NULLS LAST
                ) AS land_segments
                FROM (
                    SELECT *
                    FROM (
                        SELECT l.*,
                               ROW_NUMBER() OVER (
                                   PARTITION BY l.land_segment_id,
                                                l.property_value_year,
                                                l.land_type
                                   ORDER BY l.property_value_year DESC NULLS LAST,
                                            l.market_value DESC NULLS LAST,
                                            l.land_segment_id
                               ) AS rn
                        FROM land l
                        WHERE l.parcel_number = s.parcel_number
                    ) ranked_land
                    WHERE rn = 1
                ) lf
            ) land ON TRUE
            LEFT JOIN LATERAL (
                SELECT json_agg(
                    json_strip_nulls(
                        json_build_object(
                            'improvement_id', improvement_filtered.improvement_id,
                            'description', improvement_filtered.description,
                            'building_style', improvement_filtered.building_style,
                            'condition_code', improvement_filtered.condition_code,
                            'improvement_value', improvement_filtered.improvement_value,
                            'total_living_area', improvement_filtered.total_living_area,
                            'actual_year_built', improvement_filtered.actual_year_built,
                            'effective_year_built', improvement_filtered.effective_year_built
                        )
                    )
                    ORDER BY improvement_filtered.improvement_id,
                             improvement_filtered.effective_year_built DESC NULLS LAST,
                             improvement_filtered.actual_year_built DESC NULLS LAST
                ) AS improvements
                FROM (
                    SELECT *
                    FROM (
                        SELECT i.*,
                               ROW_NUMBER() OVER (
                                   PARTITION BY i.improvement_id
                                   ORDER BY
                                       i.effective_year_built DESC NULLS LAST,
                                       i.actual_year_built DESC NULLS LAST
                        ) AS rn
                FROM improvements i
                WHERE i.parcel_number = s.parcel_number
            ) ranked_improvements
            WHERE rn = 1
        ) improvement_filtered
            ) improvements ON TRUE
            {where_clause}
            ORDER BY {base_column} {order_direction} NULLS LAST, s.sale_id DESC NULLS LAST
            LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(count_sql, args)
            total = cursor.fetchone()[0]

        with connection.cursor() as cursor:
            cursor.execute(data_sql, args + [limit])
            rows = _dictfetchall(cursor)

        results: List[Dict[str, Any]] = []
        for row in rows:
            normalized = {key: _normalize(value) for key, value in row.items()}
            land_segments = _coalesce_list(normalized.pop("land_segments", []))
            improvements = _coalesce_list(normalized.pop("improvements", []))

            land_total_acres = sum(
                segment.get("size_acres") or 0 for segment in land_segments if isinstance(segment, dict)
            ) or normalized.get("acres")
            land_total_market_value = sum(
                segment.get("market_value") or 0 for segment in land_segments if isinstance(segment, dict)
            ) or normalized.get("total_market_value")

            results.append(
                {
                    "parcel_number": normalized.get("parcel_number"),
                    "sale": {
                        "sale_id": normalized.get("sale_id"),
                        "account_number": normalized.get("account_number"),
                        "seller_name": normalized.get("seller_name"),
                        "buyer_name": normalized.get("buyer_name"),
                        "sale_price": normalized.get("sale_price"),
                        "sale_date": normalized.get("sale_date"),
                        "sale_type": normalized.get("sale_type"),
                        "recording_number": normalized.get("recording_number"),
                        "deed_type": normalized.get("deed_type"),
                        "deed_date": normalized.get("deed_date"),
                        "revaluation_area": normalized.get("revaluation_area"),
                        "excise_number": normalized.get("excise_number"),
                    },
                    "parcel": {
                        "address": normalized.get("address"),
                        "neighborhood_code": normalized.get("neighborhood_code"),
                        "land_use_code": normalized.get("land_use_code"),
                        "property_type": normalized.get("property_type"),
                        "city_district": normalized.get("city_district"),
                        "school_district": normalized.get("school_district"),
                        "fire_district": normalized.get("fire_district"),
                        "assessed_value": normalized.get("assessed_value"),
                        "market_value": normalized.get("total_market_value"),
                        "taxable_value": normalized.get("taxable_value"),
                        "acres": normalized.get("acres"),
                        "year_built": normalized.get("year_built"),
                        "effective_year_built": normalized.get("eff_year_built"),
                        "bedrooms": normalized.get("bedrooms"),
                        "bathrooms": normalized.get("bathrooms"),
                        "living_area": normalized.get("living_area"),
                    },
                    "land": {
                        "total_acres": land_total_acres,
                        "total_market_value": land_total_market_value,
                        "segments": land_segments,
                    },
                    "improvements": improvements,
                }
            )

        return Response(
            {
                "count": total,
                "limit": limit,
                "sort": {"field": sort_key, "direction": order_direction.lower()},
                "results": results,
            }
        )


class ParcelSearchView(APIView):
    permission_classes = [AllowAny]

    BASE_SEARCH_SQL = """
        FROM master_parcel mp
        LEFT JOIN LATERAL (
            SELECT s.sale_price,
                   s.sale_date
            FROM sales s
            WHERE s.parcel_number = mp.parcel_number
            ORDER BY s.sale_date DESC NULLS LAST
            LIMIT 1
        ) latest_sale ON TRUE
    """

    def get(self, request) -> Response:
        page = _parse_positive_int(request.query_params.get("page"), 1)
        page_size = _parse_positive_int(request.query_params.get("page_size"), settings.REST_FRAMEWORK.get("PAGE_SIZE", 25), max_value=250)
        offset = (page - 1) * page_size

        clauses, args = _build_base_search_filters(request.query_params)
        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        count_sql = f"SELECT COUNT(*) {self.BASE_SEARCH_SQL} {where_clause}"
        data_sql = f"""
            SELECT
                mp.parcel_number,
                mp.situs_address AS address,
                mp.assessed_value,
                mp.total_market_value,
                mp.acres,
                mp.city_district,
                mp.year_built,
                latest_sale.sale_price AS last_sale_price,
                latest_sale.sale_date AS last_sale_date
            {self.BASE_SEARCH_SQL}
            {where_clause}
            ORDER BY mp.assessed_value DESC NULLS LAST, mp.parcel_number
            OFFSET %s LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(count_sql, args)
            total = cursor.fetchone()[0]

        with connection.cursor() as cursor:
            cursor.execute(data_sql, args + [offset, page_size])
            records = [_normalize(row) for row in _dictfetchall(cursor)]

        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": records,
            }
        )


class ParcelSummaryView(APIView):
    permission_classes = [AllowAny]

    GROUP_BY_FIELDS = {
        "city_district": "mp.city_district",
        "school_district": "mp.school_district",
        "fire_district": "mp.fire_district",
        "neighborhood_code": "mp.hood_code",
        "levy_code": "mp.levy_code",
    }

    METRICS = {
        "avg_assessed_value": ("AVG(mp.assessed_value)", "average_assessed_value"),
        "avg_market_value": ("AVG(mp.total_market_value)", "average_market_value"),
        "total_assessed_value": ("SUM(mp.assessed_value)", "total_assessed_value"),
        "parcel_count": ("COUNT(*)", "parcel_count"),
    }

    def get(self, request) -> Response:
        group_by_key = request.query_params.get("group_by")
        metric_key = request.query_params.get("metric")

        if group_by_key not in self.GROUP_BY_FIELDS:
            raise ValidationError(f"Unknown group_by '{group_by_key}'. Choices: {', '.join(self.GROUP_BY_FIELDS)}")
        if metric_key not in self.METRICS:
            raise ValidationError(f"Unknown metric '{metric_key}'. Choices: {', '.join(self.METRICS)}")

        group_expr = self.GROUP_BY_FIELDS[group_by_key]
        metric_expr, metric_alias = self.METRICS[metric_key]
        limit = _parse_positive_int(request.query_params.get("limit"), 50, max_value=200)

        clauses, args = _build_base_search_filters(request.query_params)
        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        sql = f"""
            SELECT
                {group_expr} AS group_value,
                {metric_expr} AS metric_value,
                COUNT(*) AS parcel_count
            FROM master_parcel mp
            LEFT JOIN LATERAL (
                SELECT s.sale_price,
                       s.sale_date
                FROM sales s
                WHERE s.parcel_number = mp.parcel_number
                ORDER BY s.sale_date DESC NULLS LAST
                LIMIT 1
            ) latest_sale ON TRUE
            {where_clause}
            GROUP BY {group_expr}
            ORDER BY metric_value DESC NULLS LAST
            LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, args + [limit])
            rows = [_normalize(row) for row in _dictfetchall(cursor)]

        for row in rows:
            row[metric_alias] = row.pop("metric_value")

        return Response(
            {
                "group_by": group_by_key,
                "metric": metric_key,
                "results": rows,
            }
        )


@lru_cache(maxsize=1)
def _load_embedding_model():
    model_name = getattr(settings, "EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        logger.exception("SentenceTransformer is not available.")
        raise APIException("SentenceTransformer is not installed on the server.") from exc

    try:
        return SentenceTransformer(model_name)
    except Exception as exc:  # pragma: no cover - protects runtime failures
        logger.exception("Unable to load embedding model '%s'", model_name)
        raise APIException(f"Unable to load embedding model '{model_name}'.") from exc


class SemanticSearchView(APIView):
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        query = request.data.get("query")
        if not query or not isinstance(query, str):
            raise ValidationError({"query": "Provide a natural language query string."})

        limit = _parse_positive_int(request.data.get("limit"), 10, max_value=50)

        try:
            model = _load_embedding_model()
        except APIException as exc:
            logger.warning("Semantic search fallback: %s", exc)
            fallback_results = self._fallback_semantic_results(limit)
            return Response(
                {
                    "query": query,
                    "results": fallback_results,
                    "fallback": True,
                    "detail": str(exc),
                },
                status=status.HTTP_200_OK,
            )
        embedding = model.encode([query], normalize_embeddings=True)[0].tolist()

        # ✅ Convert to proper pgvector format: [0.123,0.456,...]
        embedding_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"

        sql = """
            SELECT
                mp.parcel_number,
                mp.situs_address AS address,
                mp.assessed_value,
                mp.total_market_value,
                mp.acres,
                mp.city_district,
                latest_sale.sale_price AS last_sale_price,
                latest_sale.sale_date AS last_sale_date,
                pg.embedding <-> %s::vector AS distance
            FROM master_parcel mp
            LEFT JOIN parcel_geometry pg ON pg.parcel_id = mp.parcel_number
            LEFT JOIN LATERAL (
                SELECT s.sale_price,
                       s.sale_date
                FROM sales s
                WHERE s.parcel_number = mp.parcel_number
                ORDER BY s.sale_date DESC NULLS LAST
                LIMIT 1
            ) latest_sale ON TRUE
            WHERE pg.embedding IS NOT NULL
              AND UPPER(TRIM(COALESCE(mp.proptype, ''))) = 'R'
            ORDER BY pg.embedding <-> %s::vector
            LIMIT %s
        """

        with connection.cursor() as cursor:
            # 👇 Explicit cast ensures pgvector understands the type
            cursor.execute(sql, [embedding_literal, embedding_literal, limit])
            rows = [_normalize(row) for row in _dictfetchall(cursor)]

        for row in rows:
            distance = row.pop("distance", None)
            if distance is not None:
                row["similarity"] = 1 / (1 + distance)

        return Response(
            {
                "query": query,
                "results": rows,
            },
            status=status.HTTP_200_OK,
        )

    def _fallback_semantic_results(self, limit: int) -> List[Dict[str, Any]]:
        sql = """
            SELECT
                mp.parcel_number,
                mp.situs_address AS address,
                mp.assessed_value,
                mp.total_market_value,
                mp.acres,
                mp.city_district,
                latest_sale.sale_price AS last_sale_price,
                latest_sale.sale_date AS last_sale_date
            FROM master_parcel mp
            LEFT JOIN LATERAL (
                SELECT s.sale_price,
                       s.sale_date
                FROM sales s
                WHERE s.parcel_number = mp.parcel_number
                ORDER BY s.sale_date DESC NULLS LAST
                LIMIT 1
            ) latest_sale ON TRUE
            WHERE mp.situs_address IS NOT NULL
              AND UPPER(TRIM(COALESCE(mp.proptype, ''))) = 'R'
            ORDER BY mp.total_market_value DESC NULLS LAST
            LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [limit])
            rows = [_normalize(row) for row in _dictfetchall(cursor)]
        for row in rows:
            row["similarity"] = None
        return rows


class NearbyParcelsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        try:
            lat = float(request.query_params.get("lat"))
            lon = float(request.query_params.get("lon"))
        except (TypeError, ValueError):
            raise ValidationError({"lat": "Latitude and longitude are required numeric values.", "lon": ""})

        try:
            radius = float(request.query_params.get("radius", request.query_params.get("radius_meters", 1000)))
        except (TypeError, ValueError):
            raise ValidationError({"radius": "Radius must be numeric in meters."})
        limit = _parse_positive_int(request.query_params.get("limit"), 50, max_value=200)

        clauses: List[str] = []
        args: List[Any] = [lon, lat, lon, lat, radius]
        point_geog = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography"
        geom_geog = "ST_Transform(pg.geom, 4326)::geography"

        min_value = request.query_params.get("min_value")
        if min_value:
            try:
                parsed = float(min_value)
            except (TypeError, ValueError):
                raise ValidationError({"min_value": "Must be a number."})
            clauses.append("mp.assessed_value >= %s")
            args.append(parsed)

        max_value = request.query_params.get("max_value")
        if max_value:
            try:
                parsed = float(max_value)
            except (TypeError, ValueError):
                raise ValidationError({"max_value": "Must be a number."})
            clauses.append("mp.assessed_value <= %s")
            args.append(parsed)

        min_acres = request.query_params.get("min_acres")
        if min_acres:
            try:
                parsed = float(min_acres)
            except (TypeError, ValueError):
                raise ValidationError({"min_acres": "Must be a number."})
            clauses.append("mp.acres >= %s")
            args.append(parsed)

        max_acres = request.query_params.get("max_acres")
        if max_acres:
            try:
                parsed = float(max_acres)
            except (TypeError, ValueError):
                raise ValidationError({"max_acres": "Must be a number."})
            clauses.append("mp.acres <= %s")
            args.append(parsed)

        where_additional = ""
        if clauses:
            where_additional = " AND " + " AND ".join(clauses)

        sql = f"""
            SELECT
                mp.parcel_number,
                mp.situs_address AS address,
                mp.assessed_value,
                mp.total_market_value,
                mp.acres,
                mp.city_district,
                ST_Distance({geom_geog}, {point_geog}) AS distance_meters
            FROM master_parcel mp
            JOIN parcel_geometry pg ON pg.parcel_id = mp.parcel_number
            WHERE pg.geom IS NOT NULL
              AND ST_DWithin({geom_geog}, {point_geog}, %s)
              AND UPPER(TRIM(COALESCE(mp.proptype, ''))) = 'R'
              {where_additional}
            ORDER BY distance_meters ASC
            LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, args + [limit])
            rows = [_normalize(row) for row in _dictfetchall(cursor)]

        return Response(
            {
                "center": {"lat": lat, "lon": lon},
                "radius_meters": radius,
                "results": rows,
            }
        )


class AppealAnalysisView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, parcel_number: str) -> Response:
        """
        GET /api/appeal_analysis/{parcel_number}/

        Returns JSON:
          - appeal_likelihood: 0–100
          - rating: weak/moderate/strong/very-strong
          - reasons: list[str]
          - debug: optional supporting details
        """
        pn = (parcel_number or "").strip()
        if not pn:
            raise ValidationError({"parcel_number": "Required"})

        try:
            subject, _ = appeals.load_subject_with_roll_context(pn)
        except ValueError:
            raise Http404("Parcel not found or unavailable")

        summary = appeals.citizen_assessment_summary(subject)

        score = int(summary.get("score") or 0)
        label = (summary.get("rating") or "").lower()
        # normalize to requested set
        label_map = {
            "weak": "weak",
            "moderate": "moderate",
            "strong": "strong",
            "very strong": "very-strong",
            "verystrong": "very-strong",
            "very_strong": "very-strong",
        }
        rating = label_map.get(label, "moderate")

        payload = {
            "appeal_likelihood": score,
            "rating": rating,
            "reasons": summary.get("reasons") or [],
            "debug": {
                "over_assessment_pct": summary.get("over_assessment_pct"),
                "comp_count": summary.get("comp_count"),
                "neighborhood": summary.get("neighborhood"),
            },
        }

        return Response(payload, status=status.HTTP_200_OK)


class AppealParcelSearchView(APIView):
    permission_classes = [AllowAny]

    MIN_QUERY_LENGTH = 3
    RESULT_LIMIT = 15

    def _base_queryset(self):
        return (
            Assessor.objects.select_related("roll")
            .filter(property_type__isnull=False)
            .filter(parcel_number__isnull=False)
            .filter(property_type__iexact="R")
            .exclude(address__isnull=True)
            .exclude(address__exact="")
            .exclude(address__icontains="nan")
        )

    def get(self, request) -> Response:
        query = (request.query_params.get("q") or "").strip()
        query_too_short = len(query) < self.MIN_QUERY_LENGTH
        results: List[Dict[str, Any]] = []
        minimal_param = (request.query_params.get("fields") or "").lower() in {"min", "minimal", "lite"} or (
            request.query_params.get("minimal") or ""
        ).lower() in {"1", "true", "yes", "y"}

        if not query_too_short:
            # If minimal mode is requested, use a very light SQL against parcel.
            if minimal_param:
                is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
                starts_with_number = bool(re.match(r"^\s*\d+", query))

                clauses: List[str] = ["p.property_type = 'R'"]
                params: List[Any] = []

                if is_parcel_like:
                    normalized = query.upper().replace(" ", "")
                    digits_only = re.sub(r"\D", "", query)
                    parcel_filters: List[str] = []
                    if normalized:
                        parcel_filters.append("UPPER(p.parcel_number) LIKE %s")
                        params.append(normalized + "%")
                    if digits_only:
                        parcel_filters.append("UPPER(p.parcel_number) LIKE %s")
                        params.append(("P" + digits_only + "%").upper())
                    if parcel_filters:
                        clauses.append("(" + " OR ".join(parcel_filters) + ")")
                else:
                    if starts_with_number:
                        clauses.append("p.address ILIKE %s")
                        params.append(query + "%")
                    else:
                        clauses.append("p.address ILIKE %s")
                        params.append("%" + query + "%")

                where_sql = " WHERE " + " AND ".join(clauses)
                sql = f"""
                    SELECT p.parcel_number, p.address
                    FROM parcel p
                    {where_sql}
                    ORDER BY p.parcel_number
                    LIMIT %s
                """
                with connection.cursor() as cursor:
                    cursor.execute(sql, params + [self.RESULT_LIMIT])
                    rows = _dictfetchall(cursor)
                results = [_normalize(r) for r in rows]
                return Response(
                    {
                        "query": query,
                        "query_too_short": False,
                        "min_search_length": self.MIN_QUERY_LENGTH,
                        "results": results,
                        "result_count": len(results),
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                qs = self._base_queryset()

            is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
            if is_parcel_like:
                normalized = query.upper().replace(" ", "")
                digits_only = re.sub(r"\D", "", query)
                filters: List[Q] = []
                if normalized:
                    filters.append(Q(parcel_number__startswith=normalized))
                if digits_only:
                    filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
                if filters:
                    qs = qs.filter(functools.reduce(operator.or_, filters))
            else:
                starts_with_number = bool(re.match(r"^\s*\d+", query))
                if starts_with_number:
                    qs = qs.filter(address__istartswith=query)
                else:
                    qs = qs.filter(address__icontains=query)

            current_year = appeals.current_assessment_year()
            if current_year:
                qs = qs.filter(roll__year=current_year)

            for row in qs.order_by("parcel_number")[: self.RESULT_LIMIT]:
                record = {
                    "parcel_number": (row.parcel_number or "").strip(),
                    "address": row.address,
                    "city_district": row.city_district,
                    "assessed_value": row.assessed_value,
                    "sale_price": row.sale_price,
                    "sale_date": row.sale_date,
                    "assessment_year": row.roll.year if row.roll else current_year,
                    "bedrooms": row.bedrooms,
                    "bathrooms": row.bathrooms,
                    "living_area_sqft": row.living_area,
                    "acres": row.acres,
                }
                results.append(_normalize(record))

        return Response(
            {
                "query": query,
                "query_too_short": query_too_short,
                "min_search_length": self.MIN_QUERY_LENGTH,
                "results": results,
                "result_count": len(results),
            },
            status=status.HTTP_200_OK,
        )


class AppealSubjectView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, parcel_number: str) -> Response:
        pn = (parcel_number or "").strip()
        if not pn:
            raise ValidationError({"parcel_number": "Required"})

        try:
            subject, roll_year = appeals.load_subject_with_roll_context(pn)
        except ValueError:
            raise Http404("Parcel not found.")

        metadata = subject.metadata if isinstance(subject.metadata, dict) else {}
        assessor_meta = metadata.get("assessor") if isinstance(metadata.get("assessor"), dict) else {}
        assessed_value = metadata.get("assessed_value") or subject.assessed_value

        subject_payload = {
            "parcel_number": subject.parcel_number,
            "address": subject.address,
            "valuation": {
                "assessed": assessed_value,
            },
            "structure": {
                "bedrooms": subject.bedrooms,
                "bathrooms": subject.bathrooms,
                "living_area_sqft": subject.living_area,
                "year_built": subject.year_built,
                "effective_year_built": subject.effective_year_built,
            },
            "location": {
                "acres": subject.acres,
            },
        }

        assessment = {
            "roll_year": metadata.get("assessment_roll_year") or roll_year,
            "assessed_value": assessed_value,
            "prior_roll_year": assessor_meta.get("prior_assessment_year"),
            "prior_assessed_value": assessor_meta.get("prior_assessed_value"),
            "change_pct": metadata.get("assessed_change_pct"),
        }

        neighborhood = appeals.get_subject_neighborhood_snapshot(subject)

        return Response(
            {
                "subject": _normalize(subject_payload),
                "assessment": _normalize(assessment),
                "neighborhood": _normalize(neighborhood),
            },
            status=status.HTTP_200_OK,
        )


class AppealComparablesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, parcel_number: str) -> Response:
        pn = (parcel_number or "").strip()
        if not pn:
            raise ValidationError({"parcel_number": "Required"})

        try:
            subject, _ = appeals.load_subject_with_roll_context(pn)
        except ValueError:
            raise Http404("Parcel not found.")

        count_param = request.query_params.get("count")
        try:
            requested_count = int(count_param) if count_param is not None else appeals.INITIAL_COMPARABLE_LIMIT
        except (TypeError, ValueError):
            raise ValidationError({"count": "Must be an integer."})

        display_limit = (
            appeals.EXTENDED_COMPARABLE_LIMIT
            if requested_count >= appeals.EXTENDED_COMPARABLE_LIMIT
            else appeals.INITIAL_COMPARABLE_LIMIT
        )

        comparables, radius_used = appeals._comparable_candidates(subject, display_limit)
        summary = appeals.citizen_assessment_summary(
            subject,
            comparables=comparables,
            radius_meters=radius_used,
            limit=display_limit,
        )

        payload_comps = [self._serialize_comparable(comp) for comp in comparables]

        over_pct = summary.get("over_assessment_pct")
        comp_count = summary.get("comp_count") or 0
        neighborhood = summary.get("neighborhood") or {}
        neigh_diff = summary.get("neigh_diff_pct")
        avg_change_pct = neighborhood.get("avg_increase_pct")
        your_change_pct = appeals.extract_assessment_change_pct(subject.metadata)
        if your_change_pct is None and avg_change_pct is not None and neigh_diff is not None:
            your_change_pct = avg_change_pct + neigh_diff
        if neigh_diff is None and avg_change_pct is not None and your_change_pct is not None:
            neigh_diff = your_change_pct - avg_change_pct

        score = summary.get("score") or 0

        soft_stop = False
        soft_reasons: List[str] = []
        if over_pct is not None and over_pct < 7:
            soft_stop = True
            soft_reasons.append("Assessed value is less than ~7% above market comps.")
        if comp_count < 3:
            soft_stop = True
            soft_reasons.append("Fewer than 3 strong comparable sales are available.")
        if (neigh_diff is not None) and neigh_diff <= 0:
            soft_stop = True
            soft_reasons.append("Your assessment did not rise more than your neighborhood average.")
        if score < 45:
            soft_stop = True
            soft_reasons.append("Overall appeal likelihood is below ~45%.")

        has_more = len(comparables) == display_limit and display_limit < appeals.EXTENDED_COMPARABLE_LIMIT

        return Response(
            {
                "parcel_number": pn,
                "comparables": payload_comps,
                "score": score,
                "rating": summary.get("rating"),
                "reasons": summary.get("reasons", []),
                "over_assessment_pct": over_pct,
                "comp_count": comp_count,
                "neighborhood": _normalize(neighborhood),
                "neigh_diff_pct": neigh_diff,
                "soft_stop": soft_stop,
                "soft_reasons": soft_reasons,
                "has_more": has_more,
                "current_limit": display_limit,
                "max_limit": appeals.EXTENDED_COMPARABLE_LIMIT,
                "radius_meters_used": radius_used,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _serialize_comparable(comp: cma.ComparableResult) -> Dict[str, Any]:
        metadata = comp.snapshot.metadata if isinstance(comp.snapshot.metadata, dict) else {}
        score_payload = comp.score
        return _normalize(
            {
                "parcel_number": comp.snapshot.parcel_number,
                "address": comp.snapshot.address,
                "sale_price": comp.sale_price,
                "sale_date": comp.sale_date,
                "assessed_value": comp.assessed_value,
                "distance_miles": comp.distance_miles,
                "distance_meters": comp.distance_meters,
                "bedrooms": comp.snapshot.bedrooms,
                "bathrooms": comp.snapshot.bathrooms,
                "living_area_sqft": comp.snapshot.living_area,
                "year_built": comp.snapshot.year_built,
                "effective_year_built": comp.snapshot.effective_year_built,
                "metadata": metadata,
                "rank": comp.inclusion_rank,
                "score": score_payload.total_score if score_payload else None,
                "location_score": score_payload.location_score if score_payload else None,
                "time_score": score_payload.time_score if score_payload else None,
                "physical_score": score_payload.physical_score if score_payload else None,
            }
        )


class AppealComparableImprovementsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, parcel_number: str, comp_parcel: str) -> Response:  # pylint: disable=unused-argument
        roll_year = self._parse_optional_int(request.query_params.get("roll_year"), "roll_year")
        roll_id = self._parse_optional_int(request.query_params.get("roll_id"), "roll_id")
        assessor_style = request.query_params.get("assessor_style") or None

        improvements = cma.get_improvement_rollup(
            comp_parcel,
            roll_year=roll_year,
            roll_id=roll_id,
            assessor_building_style=assessor_style,
        )

        return Response(
            {
                "parcel_number": comp_parcel,
                "improvements": _normalize(improvements),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _parse_optional_int(value: Optional[str], field: str) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError({field: "Must be an integer."})


class CoAppraiserAdjustmentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        subject = request.data.get("subject")
        comps = request.data.get("comps") or []
        subject_pred_price = request.data.get("subject_pred_price")
        market_group = request.data.get("market_group")
        run_id = request.data.get("run_id")

        if not isinstance(subject, dict):
            raise ValidationError({"subject": "Subject payload is required."})
        if not isinstance(comps, list):
            raise ValidationError({"comps": "Comparables must be provided as a list."})
        if subject_pred_price is None:
            raise ValidationError({"subject_pred_price": "Required field."})

        try:
            payload = adjustment_engine.compute_adjustments(
                subject=subject,
                comps=comps,
                subject_pred_price=subject_pred_price,
                market_group=market_group,
                run_id=run_id,
            )
        except adjustment_engine.MissingCoefficientError as exc:
            return Response({"error_message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except adjustment_engine.AdjustmentEngineError as exc:
            raise ValidationError(str(exc))

        return Response(payload, status=status.HTTP_200_OK)


class CivicBalanceMapView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT election_year FROM public.fact_neighborhood_participation ORDER BY election_year DESC"
            )
            available_years = [row[0] for row in cursor.fetchall()]

        if not available_years:
            return Response(
                {
                    "type": "FeatureCollection",
                    "features": [],
                    "available_years": [],
                    "year": None,
                    "quartile_labels": CIVIC_BALANCE_QUARTILE_LABELS,
                },
                status=status.HTTP_200_OK,
            )

        year_param = request.query_params.get("year")
        if year_param in (None, ""):
            year = available_years[0]
        else:
            try:
                year = int(year_param)
            except (TypeError, ValueError):
                raise ValidationError({"year": "Must be an integer tax year."})

            if year not in available_years:
                raise ValidationError({"year": f"Year must be one of {available_years}."})

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    f.neighborhood_code,
                    COALESCE(ng.name, f.neighborhood_code) AS neighborhood_name,
                    f.election_year,
                    f.ballots_cast,
                    f.residential_parcels,
                    f.npi,
                    f.primary_precinct_code,
                    f.precinct_ballots_cast,
                    f.precinct_residential_parcels,
                    f.precinct_ppi,
                    f.precinct_po_box_pct,
                    f.precinct_po_box_ballots,
                    f.assignment_coverage_precinct,
                    f.ambiguous_ballots,
                    c.quartile,
                    c.quartile_label,
                    ST_AsGeoJSON(ST_Transform(f.geom_2926, 4326), 6) AS geom_geojson
                FROM public.fact_neighborhood_participation f
                LEFT JOIN public.neighborhood_participation_classification c
                  ON c.neighborhood_code = f.neighborhood_code
                 AND c.election_year = f.election_year
                LEFT JOIN public.openskagit_neighborhoodgeom ng
                  ON ng.code = f.neighborhood_code
                WHERE f.election_year = %s
                  AND ST_Intersects(f.geom_2926, (SELECT geom_2926 FROM public.skagit_county_boundary LIMIT 1))
                ORDER BY c.quartile DESC NULLS LAST, f.npi DESC NULLS LAST, f.neighborhood_code
                """,
                [year],
            )
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]

        features: List[Dict[str, Any]] = []
        for row in rows:
            geometry = row.pop("geom_geojson")
            try:
                geometry_payload = json.loads(geometry) if geometry else None
            except json.JSONDecodeError:
                geometry_payload = None

            quartile = row.get("quartile")
            if row.get("quartile_label") is None:
                row["quartile_label"] = CIVIC_BALANCE_QUARTILE_LABELS.get(quartile, "Unclassified")

            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry_payload,
                    "properties": row,
                }
            )

        return Response(
            {
                "type": "FeatureCollection",
                "year": year,
                "available_years": available_years,
                "features": features,
                "quartile_labels": CIVIC_BALANCE_QUARTILE_LABELS,
            },
            status=status.HTTP_200_OK,
        )


class VoteVectorDistrict3MapView(APIView):
    permission_classes = [AllowAny]

    DISTRICT_CODE = "3"
    DISTRICT_LABEL = "Skagit Commissioner District 3"
    NEW_CONSTRUCTION_START_YEAR = 2023
    NEW_CONSTRUCTION_END_YEAR = 2025

    def get(self, request) -> Response:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT election_year FROM public.fact_neighborhood_participation ORDER BY election_year DESC"
            )
            available_years = [int(row[0]) for row in cursor.fetchall() if row[0] is not None]

        if not available_years:
            return Response(
                {
                    "district": {
                        "code": self.DISTRICT_CODE,
                        "label": self.DISTRICT_LABEL,
                    },
                    "year": None,
                    "available_years": [],
                    "layers": {
                        "boundary": {"type": "FeatureCollection", "features": []},
                        "npi": {"type": "FeatureCollection", "features": []},
                        "precincts": {"type": "FeatureCollection", "features": []},
                        "census": {"type": "FeatureCollection", "features": []},
                        "trends": {"type": "FeatureCollection", "features": []},
                        "construction": {"type": "FeatureCollection", "features": []},
                    },
                    "summary": {
                        "neighborhoods": 0,
                        "precincts": 0,
                        "census_block_groups": 0,
                        "trend_neighborhoods": 0,
                        "trend_year": None,
                        "new_construction_parcels": 0,
                        "new_construction_start_year": self.NEW_CONSTRUCTION_START_YEAR,
                        "new_construction_end_year": self.NEW_CONSTRUCTION_END_YEAR,
                        "party_signal_precincts": 0,
                        "party_data_available": False,
                    },
                },
                status=status.HTTP_200_OK,
            )

        # District 3 page intentionally pins to the most recent election year.
        year = available_years[0]

        boundary_source = "skagit_commissioner_district_arcgis"
        boundary_warning = None
        try:
            district_geometry = _fetch_skagit_commissioner_district_geometry(self.DISTRICT_CODE)
        except Exception:
            logger.warning(
                "Falling back to county boundary for VoteVector District 3 (commissioner layer unavailable).",
                exc_info=True,
            )
            district_geometry = _load_skagit_county_boundary_geojson()
            boundary_source = "skagit_county_boundary_fallback"
            boundary_warning = (
                "Commissioner District 3 boundary service is unavailable. "
                "Showing county boundary fallback."
            )

        district_geojson_text = json.dumps(district_geometry)
        npi_features = self._load_npi_layer(district_geojson_text=district_geojson_text, year=year)
        precinct_features = self._load_precinct_layer(district_geojson_text=district_geojson_text, year=year)
        census_year, census_features = self._load_census_layer(district_geojson_text=district_geojson_text)
        trend_year, trend_features = self._load_trend_layer(district_geojson_text=district_geojson_text, year=year)
        construction_features = self._load_new_construction_layer(district_geojson_text=district_geojson_text)
        party_signal_precincts = sum(
            1
            for feature in precinct_features
            if (
                (feature.get("properties") or {}).get("major_party_votes") is not None
                and (feature.get("properties") or {}).get("major_party_votes", 0) > 0
            )
        )

        boundary_feature = {
            "type": "Feature",
            "geometry": district_geometry,
            "properties": {
                "district_code": self.DISTRICT_CODE,
                "district_label": self.DISTRICT_LABEL,
                "boundary_source": boundary_source,
            },
        }

        return Response(
            {
                "district": {
                    "code": self.DISTRICT_CODE,
                    "label": self.DISTRICT_LABEL,
                    "boundary_source": boundary_source,
                },
                "year": year,
                "available_years": available_years,
                "census_year": census_year,
                "boundary_warning": boundary_warning,
                "layers": {
                    "boundary": {"type": "FeatureCollection", "features": [boundary_feature]},
                    "npi": {"type": "FeatureCollection", "features": npi_features},
                    "precincts": {"type": "FeatureCollection", "features": precinct_features},
                    "census": {"type": "FeatureCollection", "features": census_features},
                    "trends": {"type": "FeatureCollection", "features": trend_features},
                    "construction": {"type": "FeatureCollection", "features": construction_features},
                },
                "summary": {
                    "neighborhoods": len(npi_features),
                    "precincts": len(precinct_features),
                    "census_block_groups": len(census_features),
                    "trend_neighborhoods": len(trend_features),
                    "trend_year": trend_year,
                    "new_construction_parcels": len(construction_features),
                    "new_construction_start_year": self.NEW_CONSTRUCTION_START_YEAR,
                    "new_construction_end_year": self.NEW_CONSTRUCTION_END_YEAR,
                    "party_signal_precincts": party_signal_precincts,
                    "party_data_available": party_signal_precincts > 0,
                },
            },
            status=status.HTTP_200_OK,
        )

    def _load_npi_layer(self, *, district_geojson_text: str, year: int) -> List[Dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH district_boundary AS (
                    SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2926) AS geom_2926
                ),
                clipped AS (
                    SELECT
                        f.neighborhood_code,
                        COALESCE(ng.name, f.neighborhood_code) AS neighborhood_name,
                        f.election_year,
                        f.ballots_cast,
                        f.residential_parcels,
                        f.npi,
                        f.primary_precinct_code,
                        f.precinct_ballots_cast,
                        f.precinct_residential_parcels,
                        f.precinct_ppi,
                        f.precinct_po_box_pct,
                        f.precinct_po_box_ballots,
                        f.assignment_coverage_precinct,
                        f.ambiguous_ballots,
                        c.quartile,
                        COALESCE(c.quartile_label, 'Unclassified') AS quartile_label,
                        ST_CollectionExtract(
                            ST_Intersection(ST_MakeValid(f.geom_2926), db.geom_2926),
                            3
                        ) AS geom_clip
                    FROM public.fact_neighborhood_participation f
                    CROSS JOIN district_boundary db
                    LEFT JOIN public.neighborhood_participation_classification c
                      ON c.neighborhood_code = f.neighborhood_code
                     AND c.election_year = f.election_year
                    LEFT JOIN public.openskagit_neighborhoodgeom ng
                      ON ng.code = f.neighborhood_code
                    WHERE f.election_year = %s
                      AND ST_Intersects(f.geom_2926, db.geom_2926)
                )
                SELECT
                    neighborhood_code,
                    neighborhood_name,
                    election_year,
                    ballots_cast,
                    residential_parcels,
                    npi,
                    primary_precinct_code,
                    precinct_ballots_cast,
                    precinct_residential_parcels,
                    precinct_ppi,
                    precinct_po_box_pct,
                    precinct_po_box_ballots,
                    assignment_coverage_precinct,
                    ambiguous_ballots,
                    quartile,
                    quartile_label,
                    ST_AsGeoJSON(ST_Transform(geom_clip, 4326), 6) AS geom_geojson
                FROM clipped
                WHERE geom_clip IS NOT NULL
                  AND NOT ST_IsEmpty(geom_clip)
                ORDER BY quartile DESC NULLS LAST, npi DESC NULLS LAST, neighborhood_code
                """,
                [district_geojson_text, year],
            )
            rows = _dictfetchall(cursor)
        return _rows_to_geojson_features(rows)

    def _load_precinct_layer(self, *, district_geojson_text: str, year: int) -> List[Dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH district_boundary AS (
                    SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2926) AS geom_2926
                ),
                party_votes AS (
                    SELECT
                        rpl.prec_code,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(vtr.party, '')))
                                IN ('DEMOCRAT', 'DEMOCRATIC', 'DEM', 'D')
                        ) AS dem_votes,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(vtr.party, '')))
                                IN ('REPUBLICAN', 'REP', 'R', 'GOP')
                        ) AS rep_votes,
                        COUNT(*) FILTER (
                            WHERE TRIM(COALESCE(vtr.party, '')) <> ''
                              AND UPPER(TRIM(COALESCE(vtr.party, '')))
                                  NOT IN (
                                      'DEMOCRAT', 'DEMOCRATIC', 'DEM', 'D',
                                      'REPUBLICAN', 'REP', 'R', 'GOP'
                                  )
                        ) AS other_votes
                    FROM public.openskagit_voterturnoutraw vtr
                    JOIN public.openskagit_voterelection ve
                      ON ve.id = vtr.election_id
                    JOIN public.reference_precinct_lookup rpl
                      ON rpl.norm_prec_name = vtr.normalized_precinct
                     AND rpl.norm_county = 'SKAGIT'
                    WHERE EXTRACT(YEAR FROM ve.election_date)::int = %s
                    GROUP BY rpl.prec_code
                ),
                clipped AS (
                    SELECT
                        rvp.prec_code,
                        COALESCE(NULLIF(rvp.prec_name, ''), rvp.prec_code::text) AS precinct_name,
                        %s::int AS election_year,
                        COALESCE(fpt.ballots_cast, 0) AS ballots_cast,
                        ppi.residential_parcels,
                        ppi.ppi AS turnout_rate,
                        ppi.po_box_pct,
                        ppi.po_box_ballots,
                        COALESCE(pv.dem_votes, 0) AS dem_votes,
                        COALESCE(pv.rep_votes, 0) AS rep_votes,
                        COALESCE(pv.other_votes, 0) AS other_votes,
                        CASE
                            WHEN (COALESCE(pv.dem_votes, 0) + COALESCE(pv.rep_votes, 0)) > 0 THEN
                                (
                                    COALESCE(pv.dem_votes, 0)::float
                                    - COALESCE(pv.rep_votes, 0)::float
                                )
                                / NULLIF(
                                    (
                                        COALESCE(pv.dem_votes, 0)
                                        + COALESCE(pv.rep_votes, 0)
                                    )::float,
                                    0
                                )
                            ELSE NULL
                        END AS dem_margin,
                        CASE
                            WHEN (COALESCE(pv.dem_votes, 0) + COALESCE(pv.rep_votes, 0)) = 0
                                THEN 'No major-party signal'
                            WHEN COALESCE(pv.dem_votes, 0) > COALESCE(pv.rep_votes, 0)
                                THEN 'Leans Democratic'
                            WHEN COALESCE(pv.rep_votes, 0) > COALESCE(pv.dem_votes, 0)
                                THEN 'Leans Republican'
                            ELSE 'Even split'
                        END AS party_lean,
                        ST_CollectionExtract(
                            ST_Intersection(ST_MakeValid(rvp.geom_2926), db.geom_2926),
                            3
                        ) AS geom_clip
                    FROM public.reference_votingprecinct rvp
                    CROSS JOIN district_boundary db
                    LEFT JOIN public.fact_precinct_turnout fpt
                      ON fpt.prec_code = rvp.prec_code
                     AND fpt.election_year = %s
                    LEFT JOIN public.precinct_participation_index ppi
                      ON ppi.prec_code = rvp.prec_code
                     AND ppi.election_year = %s
                    LEFT JOIN party_votes pv
                      ON pv.prec_code = rvp.prec_code
                    WHERE rvp.county_name = 'Skagit'
                      AND ST_Intersects(rvp.geom_2926, db.geom_2926)
                )
                SELECT
                    prec_code,
                    precinct_name,
                    election_year,
                    ballots_cast,
                    residential_parcels,
                    turnout_rate,
                    po_box_pct,
                    po_box_ballots,
                    dem_votes,
                    rep_votes,
                    other_votes,
                    (COALESCE(dem_votes, 0) + COALESCE(rep_votes, 0)) AS major_party_votes,
                    dem_margin,
                    party_lean,
                    ST_AsGeoJSON(ST_Transform(geom_clip, 4326), 6) AS geom_geojson
                FROM clipped
                WHERE geom_clip IS NOT NULL
                  AND NOT ST_IsEmpty(geom_clip)
                ORDER BY ballots_cast DESC NULLS LAST, prec_code
                """,
                [district_geojson_text, year, year, year, year],
            )
            rows = _dictfetchall(cursor)
        return _rows_to_geojson_features(rows)

    def _load_census_layer(self, *, district_geojson_text: str) -> Tuple[Optional[int], List[Dict[str, Any]]]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT MAX(year) FROM public.reference_census_acs")
            census_year_row = cursor.fetchone()
            census_year = census_year_row[0] if census_year_row else None

        if census_year is None:
            return None, []

        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH district_boundary AS (
                    SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2926) AS geom_2926
                ),
                clipped AS (
                    SELECT
                        cbg.geoid,
                        cbg.namelsad,
                        acs.year AS census_year,
                        acs.population,
                        acs.median_income,
                        acs.median_home_value,
                        acs.median_rent,
                        acs.edu_bachelors,
                        acs.edu_masters,
                        acs.edu_professional,
                        acs.edu_doctorate,
                        CASE
                            WHEN acs.population > 0 THEN
                                (
                                    COALESCE(acs.edu_bachelors, 0)
                                    + COALESCE(acs.edu_masters, 0)
                                    + COALESCE(acs.edu_professional, 0)
                                    + COALESCE(acs.edu_doctorate, 0)
                                )::float / NULLIF(acs.population::float, 0)
                            ELSE NULL
                        END AS higher_ed_share,
                        ST_CollectionExtract(
                            ST_Intersection(ST_MakeValid(cbg.geometry), db.geom_2926),
                            3
                        ) AS geom_clip
                    FROM public.reference_census_block_groups cbg
                    CROSS JOIN district_boundary db
                    JOIN public.reference_census_acs acs
                      ON acs.geoid = cbg.geoid
                     AND acs.year = %s
                    WHERE cbg.countyfp = '057'
                      AND ST_Intersects(cbg.geometry, db.geom_2926)
                )
                SELECT
                    geoid,
                    namelsad,
                    census_year,
                    population,
                    median_income,
                    median_home_value,
                    median_rent,
                    edu_bachelors,
                    edu_masters,
                    edu_professional,
                    edu_doctorate,
                    higher_ed_share,
                    ST_AsGeoJSON(ST_Transform(geom_clip, 4326), 6) AS geom_geojson
                FROM clipped
                WHERE geom_clip IS NOT NULL
                  AND NOT ST_IsEmpty(geom_clip)
                ORDER BY population DESC NULLS LAST, geoid
                """,
                [district_geojson_text, census_year],
            )
            rows = _dictfetchall(cursor)
        return int(census_year), _rows_to_geojson_features(rows)

    def _load_new_construction_layer(self, *, district_geojson_text: str) -> List[Dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH district_boundary AS (
                    SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2926) AS geom_2926
                ),
                clipped AS (
                    SELECT
                        a.parcel_number,
                        a.address,
                        a.property_type,
                        a.land_use_description,
                        a.neighborhood_code,
                        a.year_built::int AS year_built,
                        a.eff_year_built::int AS eff_year_built,
                        a.total_market_value,
                        a.assessed_value,
                        a.taxable_value,
                        a.building_value,
                        a.acres,
                        ST_CollectionExtract(
                            ST_Intersection(ST_MakeValid(a.geom_2926), db.geom_2926),
                            3
                        ) AS geom_clip
                    FROM public.assessor a
                    CROSS JOIN district_boundary db
                    WHERE a.geom_2926 IS NOT NULL
                      AND a.year_built BETWEEN %s AND %s
                      AND ST_Intersects(a.geom_2926, db.geom_2926)
                ),
                points AS (
                    SELECT
                        parcel_number,
                        address,
                        property_type,
                        land_use_description,
                        neighborhood_code,
                        year_built,
                        eff_year_built,
                        total_market_value,
                        assessed_value,
                        taxable_value,
                        building_value,
                        acres,
                        ST_Transform(ST_PointOnSurface(geom_clip), 4326) AS centroid_4326
                    FROM clipped
                    WHERE geom_clip IS NOT NULL
                      AND NOT ST_IsEmpty(geom_clip)
                )
                SELECT
                    parcel_number,
                    address,
                    property_type,
                    land_use_description,
                    neighborhood_code,
                    year_built,
                    eff_year_built,
                    total_market_value,
                    assessed_value,
                    taxable_value,
                    building_value,
                    acres,
                    ST_X(centroid_4326) AS centroid_lon,
                    ST_Y(centroid_4326) AS centroid_lat,
                    ST_AsGeoJSON(centroid_4326, 6) AS geom_geojson
                FROM points
                ORDER BY year_built DESC, total_market_value DESC NULLS LAST, parcel_number
                """,
                [
                    district_geojson_text,
                    self.NEW_CONSTRUCTION_START_YEAR,
                    self.NEW_CONSTRUCTION_END_YEAR,
                ],
            )
            rows = _dictfetchall(cursor)
        return _rows_to_geojson_features(rows)

    def _load_trend_layer(
        self,
        *,
        district_geojson_text: str,
        year: int,
    ) -> Tuple[Optional[int], List[Dict[str, Any]]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(
                    MAX(value_year) FILTER (WHERE value_year <= %s),
                    MAX(value_year)
                )
                FROM public.openskagit_neighborhoodtrend
                """,
                [year],
            )
            trend_year_row = cursor.fetchone()
            trend_year = trend_year_row[0] if trend_year_row else None

        if trend_year is None:
            return None, []

        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH district_boundary AS (
                    SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2926) AS geom_2926
                ),
                clipped AS (
                    SELECT
                        f.neighborhood_code,
                        COALESCE(ng.name, f.neighborhood_code) AS neighborhood_name,
                        nt.value_year,
                        nt.median_market_total,
                        nt.median_tax_amount,
                        nt.yoy_change_total,
                        nt.yoy_change_tax,
                        nt.stability_score,
                        nt.boom_bust_flag,
                        ST_CollectionExtract(
                            ST_Intersection(ST_MakeValid(f.geom_2926), db.geom_2926),
                            3
                        ) AS geom_clip
                    FROM public.fact_neighborhood_participation f
                    CROSS JOIN district_boundary db
                    LEFT JOIN public.openskagit_neighborhoodtrend nt
                      ON nt.hood_id = f.neighborhood_code
                     AND nt.value_year = %s
                    LEFT JOIN public.openskagit_neighborhoodgeom ng
                      ON ng.code = f.neighborhood_code
                    WHERE f.election_year = %s
                      AND ST_Intersects(f.geom_2926, db.geom_2926)
                )
                SELECT
                    neighborhood_code,
                    neighborhood_name,
                    value_year,
                    median_market_total,
                    median_tax_amount,
                    yoy_change_total,
                    yoy_change_tax,
                    stability_score,
                    boom_bust_flag,
                    ST_AsGeoJSON(ST_Transform(geom_clip, 4326), 6) AS geom_geojson
                FROM clipped
                WHERE geom_clip IS NOT NULL
                  AND NOT ST_IsEmpty(geom_clip)
                ORDER BY yoy_change_total DESC NULLS LAST, neighborhood_code
                """,
                [district_geojson_text, trend_year, year],
            )
            rows = _dictfetchall(cursor)
        return int(trend_year), _rows_to_geojson_features(rows)


def _load_regression_v1_diagnostics(experiment: ExperimentRun) -> Optional[Dict[str, Any]]:
    if experiment.diagnostics_path and os.path.exists(experiment.diagnostics_path):
        try:
            with open(experiment.diagnostics_path, "r") as handle:
                payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            return None
    if experiment.run_id:
        return load_run_payload(experiment.run_id)
    return None


def _serialize_regression_v1_run(experiment: ExperimentRun, diagnostics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    diagnostics = diagnostics or {}
    cfg = experiment.full_config.get("settings", {}) if isinstance(experiment.full_config, dict) else {}
    if not cfg and isinstance(diagnostics.get("settings"), dict):
        cfg = diagnostics["settings"]

    return {
        "run_id": experiment.run_id or str(experiment.id),
        "status": experiment.status,
        "settings": cfg,
        "segment_summary": diagnostics.get("segment_summary", []),
        "global_metrics": diagnostics.get("global_metrics", {}),
        "diagnostics_path": experiment.diagnostics_path or None,
        "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
        "completed_at": experiment.completed_at.isoformat() if experiment.completed_at else None,
        "error_message": experiment.error_message or "",
    }


class RegressionV1ConfigView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        defaults = default_regression_settings()
        return Response(
            {
                "settings": defaults.to_dict(),
                "predictor_catalog": list(DEFAULT_PREDICTORS),
                "interaction_catalog": sorted(INTERACTION_DEFINITIONS.keys()),
                "default_interactions": list(DEFAULT_INTERACTION_TERMS),
            },
            status=status.HTTP_200_OK,
        )


class RegressionV1RunsView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        settings_payload = payload.get("settings", {})
        if not isinstance(settings_payload, dict):
            raise ValidationError({"settings": "Must be an object."})

        try:
            cfg = parse_settings(settings_payload)
        except ValueError as exc:
            raise ValidationError({"settings": str(exc)}) from exc

        name = str(payload.get("name") or "").strip()
        if not name:
            stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
            name = f"Regression v1 SFR {stamp}"

        notes = str(payload.get("notes") or "").strip()
        tags_payload = payload.get("tags") or []
        if isinstance(tags_payload, str):
            tags = [token.strip() for token in tags_payload.split(",") if token.strip()]
        elif isinstance(tags_payload, list):
            tags = [str(token).strip() for token in tags_payload if str(token).strip()]
        else:
            tags = []

        full_config = {
            "pipeline": "regression_v1",
            "settings": cfg.to_dict(),
            "requested_by": request.user.username if request.user.is_authenticated else "",
        }

        experiment = ExperimentRun.objects.create(
            name=name,
            mode="sfr",
            predictor_profile="regression_v1",
            interaction_bundle="yakima_hybrid",
            market_group_col="segment_key",
            notes=notes,
            tags=tags,
            full_config=full_config,
        )

        command = [
            sys.executable,
            f"{settings.BASE_DIR}/manage.py",
            "regression_v1",
            "--experiment-id",
            str(experiment.id),
            "--settings-json",
            json.dumps(cfg.to_dict(), separators=(",", ":")),
        ]
        if bool(payload.get("dry_run")):
            command.append("--dry-run")

        try:
            subprocess.Popen(
                command,
                cwd=str(settings.BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            experiment.status = ExperimentRun.STATUS_FAILED
            experiment.error_message = str(exc)
            experiment.save(update_fields=["status", "error_message"])
            raise APIException(f"Failed to launch regression_v1 command: {exc}") from exc

        run_payload = _serialize_regression_v1_run(experiment, diagnostics=None)
        return Response(run_payload, status=status.HTTP_202_ACCEPTED)


class RegressionV1RunDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, run_id: str):
        experiment = ExperimentRun.objects.filter(id=run_id, predictor_profile="regression_v1").first()
        if experiment is None:
            raise Http404("regression_v1 run not found")

        diagnostics = _load_regression_v1_diagnostics(experiment)
        payload = _serialize_regression_v1_run(experiment, diagnostics)
        return Response(payload, status=status.HTTP_200_OK)


class RegressionV1PromoteView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, run_id: str):
        experiment = ExperimentRun.objects.filter(id=run_id, predictor_profile="regression_v1").first()
        if experiment is None:
            raise Http404("regression_v1 run not found")

        if experiment.status != ExperimentRun.STATUS_COMPLETED:
            raise ValidationError({"run_id": "Run must be completed before promotion."})

        diagnostics = _load_regression_v1_diagnostics(experiment)
        if not diagnostics:
            raise ValidationError({"run_id": "Diagnostics payload not found for this run."})

        settings_json = diagnostics.get("settings", {})
        coefficients_json = diagnostics.get("coefficients", [])
        segments_json = diagnostics.get("segment_summary", [])
        global_metrics_json = diagnostics.get("global_metrics", {})
        segment_map_json = diagnostics.get("segment_map", [])

        if not isinstance(settings_json, dict):
            raise ValidationError({"run_id": "Diagnostics settings payload is invalid."})

        mode = str(settings_json.get("mode") or "sfr").lower()
        warnings: List[str] = []
        if not segments_json:
            warnings.append("Promoted model has zero segments.")

        with transaction.atomic():
            RegressionPublishedModel.objects.filter(mode=mode, is_active=True).update(is_active=False)
            published = RegressionPublishedModel.objects.create(
                mode=mode,
                run_id=experiment.run_id or str(experiment.id),
                settings_json=settings_json,
                coefficients_json=coefficients_json if isinstance(coefficients_json, list) else [],
                segments_json=segments_json if isinstance(segments_json, list) else [],
                global_metrics_json=global_metrics_json if isinstance(global_metrics_json, dict) else {},
                segment_map_json=segment_map_json if isinstance(segment_map_json, list) else [],
                is_active=True,
                promoted_at=timezone.now(),
                promoted_by=request.user if request.user.is_authenticated else None,
                diagnostics_path=experiment.diagnostics_path or "",
                notes=str(request.data.get("notes") or "").strip(),
            )

        return Response(
            {
                "run_id": experiment.run_id or str(experiment.id),
                "published_model_id": published.id,
                "promoted_at": published.promoted_at.isoformat() if published.promoted_at else None,
                "promoted_by": request.user.username if request.user.is_authenticated else "",
                "warnings": warnings,
            },
            status=status.HTTP_200_OK,
        )


class RegressionV1PredictView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        parcel_number = str(payload.get("parcel_number") or "").strip()
        if not parcel_number:
            raise ValidationError({"parcel_number": "Required."})

        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            published = RegressionPublishedModel.objects.filter(run_id=run_id).order_by("-promoted_at", "-created_at").first()
        else:
            published = RegressionPublishedModel.objects.filter(mode="sfr", is_active=True).order_by("-promoted_at", "-created_at").first()

        if published is None:
            raise Http404("No published regression_v1 model found.")

        model_payload = {
            "settings": published.settings_json,
            "coefficients": published.coefficients_json,
            "segment_summary": published.segments_json,
            "segment_map": published.segment_map_json,
        }

        anchor_raw = str(payload.get("anchor_date") or "").strip()
        anchor_override = None
        if anchor_raw:
            try:
                anchor_override = date.fromisoformat(anchor_raw)
            except ValueError as exc:
                raise ValidationError({"anchor_date": "Must be YYYY-MM-DD."}) from exc

        try:
            prediction = predict_from_published_payload(
                payload=model_payload,
                parcel_number=parcel_number,
                anchor_date_override=anchor_override,
            )
        except ValueError as exc:
            raise ValidationError({"error": str(exc)}) from exc

        prediction.update(
            {
                "run_id": published.run_id,
                "published_model_id": published.id,
            }
        )
        return Response(prediction, status=status.HTTP_200_OK)


def _api_error_payload(error: str, details: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": error}
    if details:
        payload["details"] = details
    return payload


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


def _serialize_youtube_meeting_job(job: YoutubeMeetingAnalysisJob) -> dict[str, Any]:
    result_payload: dict[str, Any] = {}
    if job.status == YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED and isinstance(job.result_json, dict):
        result_payload = job.result_json

    return {
        "id": str(job.id),
        "status": job.status,
        "status_detail": job.status_detail,
        "progress_stage": job.progress_stage,
        "progress_percent": int(job.progress_percent or 0),
        "youtube_url": job.youtube_url,
        "youtube_video_id": job.youtube_video_id,
        "requested_at": job.requested_at.isoformat() if job.requested_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message or "",
        "result_schema_version": job.result_schema_version,
        "result": result_payload,
    }


def _launch_youtube_meeting_job(job: YoutubeMeetingAnalysisJob) -> None:
    command = [
        sys.executable,
        f"{settings.BASE_DIR}/manage.py",
        "process_youtube_meeting_job",
        "--job-id",
        str(job.id),
    ]
    subprocess.Popen(
        command,
        cwd=str(settings.BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class YoutubeMeetingJobsView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}

        youtube_url = str(payload.get("youtube_url") or "").strip()
        if not youtube_url:
            return Response(
                _api_error_payload("invalid_request", {"youtube_url": "Required."}),
                status=status.HTTP_400_BAD_REQUEST,
            )

        youtube_video_id = _extract_video_id(youtube_url)
        if not youtube_video_id:
            return Response(
                _api_error_payload("invalid_request", {"youtube_url": "Must be a valid YouTube URL or ID."}),
                status=status.HTTP_400_BAD_REQUEST,
            )

        canonical_url = f"https://www.youtube.com/watch?v={youtube_video_id}"
        force = _coerce_bool(payload.get("force"))
        meeting_context_raw = payload.get("meeting_context")
        meeting_context = meeting_context_raw if isinstance(meeting_context_raw, dict) else {}
        normalized_meeting_context = {
            "body_name": str(meeting_context.get("body_name") or "").strip() or "City Council",
            "roll_call_hint": (
                str(meeting_context.get("roll_call_hint") or "").strip()
                or "Roll call usually happens at the beginning of the meeting, often in the first 2-5 minutes."
            ),
        }

        model_name = str(getattr(settings, "YOUTUBE_MEETING_GEMINI_MODEL", "gemini-2.0-flash") or "").strip()
        if not model_name:
            model_name = "gemini-2.0-flash"

        fingerprint = build_analysis_fingerprint(
            youtube_video_id=youtube_video_id,
            model_name=model_name,
        )

        in_flight = (
            YoutubeMeetingAnalysisJob.objects.filter(
                analysis_fingerprint=fingerprint,
                status__in=[
                    YoutubeMeetingAnalysisJob.STATUS_PENDING,
                    YoutubeMeetingAnalysisJob.STATUS_RUNNING,
                ],
            )
            .order_by("-requested_at")
            .first()
        )
        if in_flight is not None:
            status_url = reverse("youtube-meeting-job-detail", kwargs={"job_id": in_flight.id})
            return Response(
                {
                    "ok": True,
                    "job_id": str(in_flight.id),
                    "status": in_flight.status,
                    "reused": True,
                    "status_url": status_url,
                    "result": _serialize_youtube_meeting_job(in_flight).get("result", {}),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        if not force:
            latest_success = (
                YoutubeMeetingAnalysisJob.objects.filter(
                    analysis_fingerprint=fingerprint,
                    status=YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED,
                )
                .order_by("-requested_at")
                .first()
            )
            if latest_success is not None:
                status_url = reverse("youtube-meeting-job-detail", kwargs={"job_id": latest_success.id})
                return Response(
                    {
                        "ok": True,
                        "job_id": str(latest_success.id),
                        "status": latest_success.status,
                        "reused": True,
                        "status_url": status_url,
                        "result": _serialize_youtube_meeting_job(latest_success).get("result", {}),
                    },
                    status=status.HTTP_200_OK,
                )

        job = YoutubeMeetingAnalysisJob(
            requested_by=request.user if request.user.is_authenticated else None,
            youtube_url=canonical_url,
            youtube_video_id=youtube_video_id,
            status=YoutubeMeetingAnalysisJob.STATUS_PENDING,
            status_detail="Queued for meeting analysis.",
            progress_stage="queued",
            progress_percent=0,
            analysis_fingerprint=fingerprint,
            model_name=model_name,
            prompt_version="",
            prompt_hash="",
            result_schema_version="council_meeting_analysis.v1",
            result_json={"_request": {"meeting_context": normalized_meeting_context}},
            error_message="",
        )
        job.save()

        try:
            _launch_youtube_meeting_job(job)
        except OSError as exc:
            job.status = YoutubeMeetingAnalysisJob.STATUS_FAILED
            job.status_detail = "Unable to queue background job."
            job.progress_stage = "failed"
            job.progress_percent = 1
            job.error_message = str(exc).strip()[:4000]
            job.failure_count = int(job.failure_count or 0) + 1
            job.completed_at = timezone.now()
            job.save(
                update_fields=[
                    "status",
                    "status_detail",
                    "progress_stage",
                    "progress_percent",
                    "error_message",
                    "failure_count",
                    "completed_at",
                    "updated_at",
                ]
            )
            return Response(
                _api_error_payload(
                    "internal_error",
                    {"message": "Unable to queue meeting analysis job.", "job_id": str(job.id)},
                ),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        status_url = reverse("youtube-meeting-job-detail", kwargs={"job_id": job.id})
        return Response(
            {
                "ok": True,
                "job_id": str(job.id),
                "status": job.status,
                "reused": False,
                "status_url": status_url,
                "result": {},
            },
            status=status.HTTP_202_ACCEPTED,
        )


class YoutubeMeetingJobDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, job_id):
        job = YoutubeMeetingAnalysisJob.objects.filter(id=job_id).first()
        if job is None:
            return Response(
                _api_error_payload("not_found", {"job_id": "Job not found."}),
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "ok": True,
                "job": _serialize_youtube_meeting_job(job),
            },
            status=status.HTTP_200_OK,
        )
