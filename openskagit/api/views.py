from __future__ import annotations

import logging
import functools
import operator
import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
from openskagit import adjustment_engine, appeals, cma
from openskagit.models import Assessor
from openskagit.neighborhood import get_neighborhood_snapshot


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


def _build_base_search_filters(params) -> Tuple[List[str], List[Any]]:
    """
    Construct WHERE clauses and parameter list for parcel search endpoints.
    """
    clauses: List[str] = ["UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'"]
    args: List[Any] = []

    address = params.get("address")
    if address:
        clauses.append("a.address ILIKE %s")
        args.append(f"%{address}%")

    parcel_number = params.get("parcel_number")
    if parcel_number:
        clauses.append("a.parcel_number = %s")
        args.append(parcel_number)

    min_value = params.get("min_value")
    if min_value:
        try:
            parsed = float(min_value)
        except (TypeError, ValueError):
            raise ValidationError({"min_value": "Must be a number."})
        clauses.append("a.assessed_value >= %s")
        args.append(parsed)

    max_value = params.get("max_value")
    if max_value:
        try:
            parsed = float(max_value)
        except (TypeError, ValueError):
            raise ValidationError({"max_value": "Must be a number."})
        clauses.append("a.assessed_value <= %s")
        args.append(parsed)

    district = params.get("district")
    if district:
        clauses.append("a.city_district = %s")
        args.append(district)

    min_year = params.get("min_year")
    if min_year:
        try:
            parsed = int(min_year)
        except (TypeError, ValueError):
            raise ValidationError({"min_year": "Must be an integer year."})
        clauses.append("a.year_built >= %s")
        args.append(parsed)

    max_year = params.get("max_year")
    if max_year:
        try:
            parsed = int(max_year)
        except (TypeError, ValueError):
            raise ValidationError({"max_year": "Must be an integer year."})
        clauses.append("a.year_built <= %s")
        args.append(parsed)

    min_acres = params.get("min_acres")
    if min_acres:
        try:
            parsed = float(min_acres)
        except (TypeError, ValueError):
            raise ValidationError({"min_acres": "Must be a number."})
        clauses.append("a.acres >= %s")
        args.append(parsed)

    max_acres = params.get("max_acres")
    if max_acres:
        try:
            parsed = float(max_acres)
        except (TypeError, ValueError):
            raise ValidationError({"max_acres": "Must be a number."})
        clauses.append("a.acres <= %s")
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


def _coalesce_list(value: Optional[Iterable[Any]]) -> List[Any]:
    if value is None:
        return []
    return list(value)


PARCEL_DETAIL_SQL = """
    SELECT
        a.parcel_number,
        a.address,
        a.assessed_value,
        a.total_market_value,
        a.taxable_value,
        a.bedrooms,
        a.bathrooms,
        a.living_area,
        a.year_built,
        a.eff_year_built,
        a.acres,
        a.city_district,
        a.school_district,
        a.fire_district,
        a.latitude,
        a.longitude,
        COALESCE(land.land_segments, '[]'::json) AS land_segments,
        COALESCE(improvements.improvements, '[]'::json) AS improvements,
        COALESCE(sales.sales_array, '[]'::json) AS sales
    FROM assessor a
    LEFT JOIN LATERAL (
        SELECT json_agg(
            json_strip_nulls(
                json_build_object(
                    'property_value_year', lf.property_value_year,
                    'land_type', lf.land_type,
                    'size_acres', lf.size_acres,
                    'size_square_feet', lf.size_square_feet,
                    'market_value', lf.market_value,
                    'market_unit_price', lf.market_unit_price,
                    'land_segment_comment', lf.land_segment_comment
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
                WHERE l.parcel_number = a.parcel_number
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
                WHERE i.parcel_number = a.parcel_number
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
                WHERE s.parcel_number = a.parcel_number
            ) ranked_sales
            WHERE rn = 1
        ) sales_filtered
    ) sales ON TRUE
    WHERE a.parcel_number = %s
      AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
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
        "neighborhood": ("a.neighborhood_code", "ASC"),
        "assessed_value": ("a.assessed_value", "DESC"),
        "market_value": ("a.total_market_value", "DESC"),
        "acres": ("a.acres", "DESC"),
        "year_built": ("a.year_built", "DESC"),
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
            "UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'",
        ]
        args: List[Any] = []

        neighborhood = params.get("neighborhood")
        if neighborhood:
            clauses.append("a.neighborhood_code = %s")
            args.append(neighborhood)

        city = params.get("city")
        if city:
            clauses.append("a.city_district = %s")
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
            clauses.append("a.land_use_code = %s")
            args.append(land_use)

        # Optional property_type will only further restrict results.
        property_type = params.get("property_type")
        if property_type:
            clauses.append("UPPER(TRIM(COALESCE(a.property_type, ''))) = UPPER(TRIM(%s))")
            args.append(property_type)

        min_acres = params.get("min_acres")
        if min_acres:
            try:
                parsed = float(min_acres)
            except (TypeError, ValueError):
                raise ValidationError({"min_acres": "Must be numeric."})
            clauses.append("a.acres >= %s")
            args.append(parsed)

        max_acres = params.get("max_acres")
        if max_acres:
            try:
                parsed = float(max_acres)
            except (TypeError, ValueError):
                raise ValidationError({"max_acres": "Must be numeric."})
            clauses.append("a.acres <= %s")
            args.append(parsed)

        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        count_sql = f"""
            SELECT COUNT(*)
            FROM sales s
            JOIN assessor a ON a.parcel_number = s.parcel_number
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
                a.address,
                a.neighborhood_code,
                a.land_use_code,
                a.property_type,
                a.city_district,
                a.school_district,
                a.fire_district,
                a.assessed_value,
                a.total_market_value,
                a.taxable_value,
                a.acres,
                a.year_built,
                a.eff_year_built,
                a.bedrooms,
                a.bathrooms,
                a.living_area,
                COALESCE(land.land_segments, '[]'::json) AS land_segments,
                COALESCE(improvements.improvements, '[]'::json) AS improvements
            FROM sales s
            JOIN assessor a ON a.parcel_number = s.parcel_number
            LEFT JOIN LATERAL (
                SELECT json_agg(
                    json_strip_nulls(
                        json_build_object(
                            'property_value_year', lf.property_value_year,
                            'land_type', lf.land_type,
                            'size_acres', lf.size_acres,
                            'size_square_feet', lf.size_square_feet,
                            'market_value', lf.market_value,
                            'market_unit_price', lf.market_unit_price,
                            'land_segment_comment', lf.land_segment_comment
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
        FROM assessor a
        LEFT JOIN LATERAL (
            SELECT s.sale_price,
                   s.sale_date
            FROM sales s
            WHERE s.parcel_number = a.parcel_number
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
                a.parcel_number,
                a.address,
                a.assessed_value,
                a.total_market_value,
                a.acres,
                a.city_district,
                a.year_built,
                latest_sale.sale_price AS last_sale_price,
                latest_sale.sale_date AS last_sale_date
            {self.BASE_SEARCH_SQL}
            {where_clause}
            ORDER BY a.assessed_value DESC NULLS LAST, a.parcel_number
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
        "city_district": "a.city_district",
        "school_district": "a.school_district",
        "fire_district": "a.fire_district",
        "neighborhood_code": "a.neighborhood_code",
        "levy_code": "a.levy_code",
    }

    METRICS = {
        "avg_assessed_value": ("AVG(a.assessed_value)", "average_assessed_value"),
        "avg_market_value": ("AVG(a.total_market_value)", "average_market_value"),
        "total_assessed_value": ("SUM(a.assessed_value)", "total_assessed_value"),
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
            FROM assessor a
            LEFT JOIN LATERAL (
                SELECT s.sale_price,
                       s.sale_date
                FROM sales s
                WHERE s.parcel_number = a.parcel_number
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
                a.parcel_number,
                a.address,
                a.assessed_value,
                a.total_market_value,
                a.acres,
                a.city_district,
                latest_sale.sale_price AS last_sale_price,
                latest_sale.sale_date AS last_sale_date,
                a.embedding <-> %s::vector AS distance
            FROM assessor a
            LEFT JOIN LATERAL (
                SELECT s.sale_price,
                       s.sale_date
                FROM sales s
                WHERE s.parcel_number = a.parcel_number
                ORDER BY s.sale_date DESC NULLS LAST
                LIMIT 1
            ) latest_sale ON TRUE
            WHERE a.embedding IS NOT NULL
              AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
            ORDER BY a.embedding <-> %s::vector
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
                a.parcel_number,
                a.address,
                a.assessed_value,
                a.total_market_value,
                a.acres,
                a.city_district,
                latest_sale.sale_price AS last_sale_price,
                latest_sale.sale_date AS last_sale_date
            FROM assessor a
            LEFT JOIN LATERAL (
                SELECT s.sale_price,
                       s.sale_date
                FROM sales s
                WHERE s.parcel_number = a.parcel_number
                ORDER BY s.sale_date DESC NULLS LAST
                LIMIT 1
            ) latest_sale ON TRUE
            WHERE a.address IS NOT NULL
              AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
            ORDER BY a.total_market_value DESC NULLS LAST
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
        geom_geog = "ST_Transform(a.geom, 4326)::geography"

        min_value = request.query_params.get("min_value")
        if min_value:
            try:
                parsed = float(min_value)
            except (TypeError, ValueError):
                raise ValidationError({"min_value": "Must be a number."})
            clauses.append("a.assessed_value >= %s")
            args.append(parsed)

        max_value = request.query_params.get("max_value")
        if max_value:
            try:
                parsed = float(max_value)
            except (TypeError, ValueError):
                raise ValidationError({"max_value": "Must be a number."})
            clauses.append("a.assessed_value <= %s")
            args.append(parsed)

        min_acres = request.query_params.get("min_acres")
        if min_acres:
            try:
                parsed = float(min_acres)
            except (TypeError, ValueError):
                raise ValidationError({"min_acres": "Must be a number."})
            clauses.append("a.acres >= %s")
            args.append(parsed)

        max_acres = request.query_params.get("max_acres")
        if max_acres:
            try:
                parsed = float(max_acres)
            except (TypeError, ValueError):
                raise ValidationError({"max_acres": "Must be a number."})
            clauses.append("a.acres <= %s")
            args.append(parsed)

        where_additional = ""
        if clauses:
            where_additional = " AND " + " AND ".join(clauses)

        sql = f"""
            SELECT
                a.parcel_number,
                a.address,
                a.assessed_value,
                a.total_market_value,
                a.acres,
                a.city_district,
                ST_Distance({geom_geog}, {point_geog}) AS distance_meters
            FROM assessor a
            WHERE a.geom IS NOT NULL
              AND ST_DWithin({geom_geog}, {point_geog}, %s)
              AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
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
