from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from django.core.cache import cache
from django.db import connection
from django.utils import timezone


CITY_LIMITS_NAME = "SEDRO-WOOLLEY"
SEDRO_WOOLLEY_PORTAL_CACHE_KEY = "openskagit:sedro_woolley:portal:v1"
SEDRO_WOOLLEY_PORTAL_CACHE_TTL_SECONDS = 60 * 10
SIGNIFICANT_PERMIT_TYPES = (
    "Accessory Dwelling Unit Permit",
    "Building-Commercial",
    "Building-Industrial",
    "Building-Live/Work",
    "Building-Mixed Use",
    "Building-Public",
    "Building-Residential",
    "Clear and Grade",
    "Demolition",
    "Excavating & Grading",
    "Excavating & Grading-SEPA",
    "Garage",
    "Manufactured Home/Modular Home",
    "Model Home Permit",
    "Residential Roof",
    "Title Elimination",
)


CITY_LIMITS_CTE = """
    WITH city_limits AS (
        SELECT
            ST_UnaryUnion(ST_Collect(geometry)) AS geom_2926,
            COALESCE(SUM("ACRES"), 0)::double precision AS city_acres
        FROM public.reference_citylimits
        WHERE "NAME" = %s
    )
"""


def _dictfetchall(cursor) -> List[Dict[str, Any]]:
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _dictfetchone(cursor) -> Dict[str, Any]:
    cols = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    if row is None:
        return {}
    return dict(zip(cols, row))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def empty_sedro_woolley_portal_context() -> Dict[str, Any]:
    return {
        "scope": {
            "type": "city_limits",
            "city_limits_name": CITY_LIMITS_NAME,
            "city_name": "Sedro-Woolley",
        },
        "generated_at": timezone.now().isoformat(),
        "overview": {
            "parcel_count": 0,
            "total_assessed_value": 0.0,
            "total_taxable_value": 0.0,
            "total_market_value": 0.0,
            "total_parcel_acres": 0.0,
            "city_acres": 0.0,
            "assessed_per_parcel": 0.0,
        },
        "sales": {
            "valid_sale_count": 0,
            "sales_last_12m": 0,
            "first_sale_date": None,
            "last_sale_date": None,
            "median_sale_price": 0.0,
            "avg_sale_price": 0.0,
            "median_price_per_sqft": 0.0,
            "timeline_years": [],
        },
        "permits": {
            "permit_count": 0,
            "permits_last_12m": 0,
            "first_permit_date": None,
            "last_permit_date": None,
            "significant_permit_count": 0,
            "significant_last_12m": 0,
            "total_fees": 0.0,
            "total_amount_due": 0.0,
            "linked_parcel_count": 0,
            "status_blank_count": 0,
            "status_nonblank_count": 0,
            "status_counts": [],
            "timeline_years": [],
            "significant_types": [],
            "recent_significant": [],
            "significant_type_reference": list(SIGNIFICANT_PERMIT_TYPES),
        },
        "civic": {
            "election_year": None,
            "precinct_count": 0,
            "neighborhood_count": 0,
            "ballots_cast": 0,
            "residential_parcels": 0,
            "avg_npi": None,
        },
        "restaurants": {
            "restaurant_count": 0,
            "avg_rating": None,
            "total_reviews": 0,
            "top_restaurants": [],
        },
    }


def _load_overview(cursor) -> Dict[str, Any]:
    cursor.execute(
        f"""
        {CITY_LIMITS_CTE},
        city_parcels AS (
            SELECT DISTINCT
                mp.parcel_number,
                mp.assessed_value,
                mp.taxable_value,
                mp.total_market_value,
                mp.acres
            FROM public.master_parcel mp
            JOIN public.openskagit_parcelgeometry pg
              ON pg.parcel_id = mp.parcel_number
            JOIN city_limits cl
              ON cl.geom_2926 IS NOT NULL
             AND pg.geom_2926 IS NOT NULL
             AND ST_Intersects(pg.geom_2926, cl.geom_2926)
        )
        SELECT
            COUNT(*)::bigint AS parcel_count,
            COALESCE(SUM(assessed_value), 0)::numeric AS total_assessed_value,
            COALESCE(SUM(taxable_value), 0)::numeric AS total_taxable_value,
            COALESCE(SUM(total_market_value), 0)::numeric AS total_market_value,
            COALESCE(SUM(acres), 0)::double precision AS total_parcel_acres,
            COALESCE((SELECT city_acres FROM city_limits), 0)::double precision AS city_acres
        FROM city_parcels
        """,
        [CITY_LIMITS_NAME],
    )
    row = _dictfetchone(cursor)
    parcel_count = _as_int(row.get("parcel_count"))
    total_assessed_value = _as_float(row.get("total_assessed_value"))
    return {
        "parcel_count": parcel_count,
        "total_assessed_value": total_assessed_value,
        "total_taxable_value": _as_float(row.get("total_taxable_value")),
        "total_market_value": _as_float(row.get("total_market_value")),
        "total_parcel_acres": _as_float(row.get("total_parcel_acres")),
        "city_acres": _as_float(row.get("city_acres")),
        "assessed_per_parcel": (total_assessed_value / parcel_count) if parcel_count else 0.0,
    }


def _load_sales(cursor) -> Dict[str, Any]:
    cursor.execute(
        f"""
        {CITY_LIMITS_CTE},
        city_parcels AS (
            SELECT DISTINCT
                mp.parcel_number,
                NULLIF(mp.living_area, 0)::double precision AS living_area
            FROM public.master_parcel mp
            JOIN public.openskagit_parcelgeometry pg
              ON pg.parcel_id = mp.parcel_number
            JOIN city_limits cl
              ON cl.geom_2926 IS NOT NULL
             AND pg.geom_2926 IS NOT NULL
             AND ST_Intersects(pg.geom_2926, cl.geom_2926)
        ),
        valid_sales AS (
            SELECT
                s.sale_date::date AS sale_date,
                s.sale_price::double precision AS sale_price,
                cp.living_area
            FROM public.sales s
            JOIN city_parcels cp
              ON cp.parcel_number = s.parcel_number
            WHERE LOWER(TRIM(COALESCE(s.sale_type, ''))) = 'valid sale'
              AND s.sale_date IS NOT NULL
              AND s.sale_price IS NOT NULL
              AND s.sale_price > 0
        )
        SELECT
            COUNT(*)::bigint AS valid_sale_count,
            MIN(sale_date) AS first_sale_date,
            MAX(sale_date) AS last_sale_date,
            COUNT(*) FILTER (
                WHERE sale_date >= CURRENT_DATE - INTERVAL '12 months'
            )::bigint AS sales_last_12m,
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY sale_price
            ) AS median_sale_price,
            AVG(sale_price) AS avg_sale_price,
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY sale_price / living_area
            ) FILTER (
                WHERE living_area IS NOT NULL AND living_area > 0
            ) AS median_price_per_sqft
        FROM valid_sales
        """,
        [CITY_LIMITS_NAME],
    )
    summary_row = _dictfetchone(cursor)

    cursor.execute(
        f"""
        {CITY_LIMITS_CTE},
        city_parcels AS (
            SELECT DISTINCT mp.parcel_number
            FROM public.master_parcel mp
            JOIN public.openskagit_parcelgeometry pg
              ON pg.parcel_id = mp.parcel_number
            JOIN city_limits cl
              ON cl.geom_2926 IS NOT NULL
             AND pg.geom_2926 IS NOT NULL
             AND ST_Intersects(pg.geom_2926, cl.geom_2926)
        ),
        valid_sales AS (
            SELECT
                s.sale_date::date AS sale_date,
                s.sale_price::double precision AS sale_price
            FROM public.sales s
            JOIN city_parcels cp
              ON cp.parcel_number = s.parcel_number
            WHERE LOWER(TRIM(COALESCE(s.sale_type, ''))) = 'valid sale'
              AND s.sale_date IS NOT NULL
              AND s.sale_price IS NOT NULL
              AND s.sale_price > 0
        )
        SELECT
            EXTRACT(YEAR FROM sale_date)::int AS sale_year,
            COUNT(*)::bigint AS sale_count,
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY sale_price
            ) AS median_sale_price
        FROM valid_sales
        WHERE sale_date >= CURRENT_DATE - INTERVAL '12 years'
        GROUP BY sale_year
        ORDER BY sale_year
        """,
        [CITY_LIMITS_NAME],
    )
    timeline_rows = _dictfetchall(cursor)
    timeline = [
        {
            "sale_year": _as_int(row.get("sale_year")),
            "sale_count": _as_int(row.get("sale_count")),
            "median_sale_price": _as_float(row.get("median_sale_price")),
        }
        for row in timeline_rows
    ]

    return {
        "valid_sale_count": _as_int(summary_row.get("valid_sale_count")),
        "sales_last_12m": _as_int(summary_row.get("sales_last_12m")),
        "first_sale_date": summary_row.get("first_sale_date"),
        "last_sale_date": summary_row.get("last_sale_date"),
        "median_sale_price": _as_float(summary_row.get("median_sale_price")),
        "avg_sale_price": _as_float(summary_row.get("avg_sale_price")),
        "median_price_per_sqft": _as_float(summary_row.get("median_price_per_sqft")),
        "timeline_years": timeline,
    }


def _load_permits(cursor) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT
            COUNT(*)::bigint AS permit_count,
            MIN(permit_date) AS first_permit_date,
            MAX(permit_date) AS last_permit_date,
            COUNT(*) FILTER (
                WHERE permit_date >= CURRENT_DATE - INTERVAL '12 months'
            )::bigint AS permits_last_12m,
            COUNT(*) FILTER (
                WHERE status IS NULL OR BTRIM(status) = ''
            )::bigint AS status_blank_count,
            COUNT(*) FILTER (
                WHERE status IS NOT NULL AND BTRIM(status) <> ''
            )::bigint AS status_nonblank_count,
            COALESCE(SUM(total_fees), 0)::numeric AS total_fees,
            COALESCE(SUM(amount_due), 0)::numeric AS total_amount_due,
            COUNT(*) FILTER (WHERE parcel_id IS NOT NULL)::bigint AS linked_parcel_count
        FROM public.openskagit_sedrowoolleypermit
        """
    )
    summary_row = _dictfetchone(cursor)

    cursor.execute(
        """
        SELECT
            COUNT(*)::bigint AS significant_permit_count,
            COUNT(*) FILTER (
                WHERE permit_date >= CURRENT_DATE - INTERVAL '12 months'
            )::bigint AS significant_last_12m
        FROM public.openskagit_sedrowoolleypermit
        WHERE permit_type = ANY(%s::text[])
        """,
        [list(SIGNIFICANT_PERMIT_TYPES)],
    )
    significant_row = _dictfetchone(cursor)

    cursor.execute(
        """
        SELECT
            permit_type,
            COUNT(*)::bigint AS permit_count
        FROM public.openskagit_sedrowoolleypermit
        WHERE permit_type = ANY(%s::text[])
        GROUP BY permit_type
        ORDER BY permit_count DESC, permit_type
        """,
        [list(SIGNIFICANT_PERMIT_TYPES)],
    )
    significant_types = [
        {
            "permit_type": _clean_text(row.get("permit_type")),
            "permit_count": _as_int(row.get("permit_count")),
        }
        for row in _dictfetchall(cursor)
    ]

    cursor.execute(
        """
        SELECT
            EXTRACT(YEAR FROM permit_date)::int AS permit_year,
            COUNT(*)::bigint AS permit_count,
            COUNT(*) FILTER (
                WHERE permit_type = ANY(%s::text[])
            )::bigint AS significant_count
        FROM public.openskagit_sedrowoolleypermit
        WHERE permit_date IS NOT NULL
          AND permit_date >= CURRENT_DATE - INTERVAL '14 years'
        GROUP BY permit_year
        ORDER BY permit_year
        """,
        [list(SIGNIFICANT_PERMIT_TYPES)],
    )
    timeline_years = [
        {
            "permit_year": _as_int(row.get("permit_year")),
            "permit_count": _as_int(row.get("permit_count")),
            "significant_count": _as_int(row.get("significant_count")),
        }
        for row in _dictfetchall(cursor)
    ]

    cursor.execute(
        """
        SELECT
            BTRIM(status) AS status,
            COUNT(*)::bigint AS permit_count
        FROM public.openskagit_sedrowoolleypermit
        WHERE status IS NOT NULL
          AND BTRIM(status) <> ''
        GROUP BY BTRIM(status)
        ORDER BY permit_count DESC, status
        LIMIT 8
        """
    )
    status_counts = [
        {
            "status": _clean_text(row.get("status")),
            "permit_count": _as_int(row.get("permit_count")),
        }
        for row in _dictfetchall(cursor)
    ]

    cursor.execute(
        """
        SELECT
            COALESCE(NULLIF(BTRIM(permit_number), ''), external_id) AS permit_number,
            permit_date,
            permit_type,
            site_address,
            NULLIF(BTRIM(status), '') AS status,
            total_fees,
            amount_due,
            detail_url
        FROM public.openskagit_sedrowoolleypermit
        WHERE permit_type = ANY(%s::text[])
        ORDER BY permit_date DESC NULLS LAST, updated_at DESC
        LIMIT 12
        """,
        [list(SIGNIFICANT_PERMIT_TYPES)],
    )
    recent_significant = [
        {
            "permit_number": _clean_text(row.get("permit_number")),
            "permit_date": row.get("permit_date"),
            "permit_type": _clean_text(row.get("permit_type")),
            "site_address": _clean_text(row.get("site_address")),
            "status": _clean_text(row.get("status")),
            "total_fees": _as_float(row.get("total_fees")),
            "amount_due": _as_float(row.get("amount_due")),
            "detail_url": _clean_text(row.get("detail_url")),
        }
        for row in _dictfetchall(cursor)
    ]

    return {
        "permit_count": _as_int(summary_row.get("permit_count")),
        "permits_last_12m": _as_int(summary_row.get("permits_last_12m")),
        "first_permit_date": summary_row.get("first_permit_date"),
        "last_permit_date": summary_row.get("last_permit_date"),
        "significant_permit_count": _as_int(significant_row.get("significant_permit_count")),
        "significant_last_12m": _as_int(significant_row.get("significant_last_12m")),
        "total_fees": _as_float(summary_row.get("total_fees")),
        "total_amount_due": _as_float(summary_row.get("total_amount_due")),
        "linked_parcel_count": _as_int(summary_row.get("linked_parcel_count")),
        "status_blank_count": _as_int(summary_row.get("status_blank_count")),
        "status_nonblank_count": _as_int(summary_row.get("status_nonblank_count")),
        "status_counts": status_counts,
        "timeline_years": timeline_years,
        "significant_types": significant_types,
        "recent_significant": recent_significant,
        "significant_type_reference": list(SIGNIFICANT_PERMIT_TYPES),
    }


def _load_civic(cursor) -> Dict[str, Any]:
    cursor.execute(
        f"""
        {CITY_LIMITS_CTE},
        latest_year AS (
            SELECT MAX(election_year)::int AS election_year
            FROM public.fact_neighborhood_participation
        ),
        city_rows AS (
            SELECT
                f.election_year,
                f.ballots_cast,
                f.residential_parcels,
                f.npi
            FROM public.fact_neighborhood_participation f
            JOIN latest_year ly
              ON ly.election_year = f.election_year
            JOIN city_limits cl
              ON cl.geom_2926 IS NOT NULL
             AND f.geom_2926 IS NOT NULL
             AND ST_Intersects(f.geom_2926, cl.geom_2926)
        )
        SELECT
            MAX(election_year)::int AS election_year,
            COUNT(*)::bigint AS neighborhood_count,
            COALESCE(SUM(ballots_cast), 0)::bigint AS ballots_cast,
            COALESCE(SUM(residential_parcels), 0)::bigint AS residential_parcels,
            AVG(npi)::double precision AS avg_npi
        FROM city_rows
        """,
        [CITY_LIMITS_NAME],
    )
    civic_row = _dictfetchone(cursor)

    cursor.execute(
        f"""
        {CITY_LIMITS_CTE}
        SELECT
            COUNT(DISTINCT vp.prec_code)::bigint AS precinct_count
        FROM public.reference_votingprecinct_base vp
        JOIN city_limits cl
          ON cl.geom_2926 IS NOT NULL
         AND vp.geom_2926 IS NOT NULL
         AND ST_Intersects(vp.geom_2926, cl.geom_2926)
        """,
        [CITY_LIMITS_NAME],
    )
    precinct_row = _dictfetchone(cursor)

    avg_npi = civic_row.get("avg_npi")
    return {
        "election_year": civic_row.get("election_year"),
        "precinct_count": _as_int(precinct_row.get("precinct_count")),
        "neighborhood_count": _as_int(civic_row.get("neighborhood_count")),
        "ballots_cast": _as_int(civic_row.get("ballots_cast")),
        "residential_parcels": _as_int(civic_row.get("residential_parcels")),
        "avg_npi": round(_as_float(avg_npi), 3) if avg_npi is not None else None,
    }


def _load_restaurants(cursor) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE active)::bigint AS restaurant_count,
            AVG(rating) FILTER (
                WHERE active AND rating IS NOT NULL
            )::double precision AS avg_rating,
            COALESCE(SUM(review_count) FILTER (WHERE active), 0)::bigint AS total_reviews
        FROM public.gastronet_restaurant
        WHERE city ILIKE 'sedro%%'
        """
    )
    summary_row = _dictfetchone(cursor)

    cursor.execute(
        """
        SELECT
            name,
            rating,
            review_count
        FROM public.gastronet_restaurant
        WHERE city ILIKE 'sedro%%'
          AND active = true
        ORDER BY review_count DESC NULLS LAST, rating DESC NULLS LAST, name
        LIMIT 6
        """
    )
    top_restaurants = [
        {
            "name": _clean_text(row.get("name")),
            "rating": _as_float(row.get("rating")),
            "review_count": _as_int(row.get("review_count")),
        }
        for row in _dictfetchall(cursor)
    ]

    avg_rating = summary_row.get("avg_rating")
    return {
        "restaurant_count": _as_int(summary_row.get("restaurant_count")),
        "avg_rating": round(_as_float(avg_rating), 2) if avg_rating is not None else None,
        "total_reviews": _as_int(summary_row.get("total_reviews")),
        "top_restaurants": top_restaurants,
    }


def load_sedro_woolley_portal_context() -> Dict[str, Any]:
    cached = cache.get(SEDRO_WOOLLEY_PORTAL_CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    payload = empty_sedro_woolley_portal_context()

    with connection.cursor() as cursor:
        payload["overview"] = _load_overview(cursor)
        payload["sales"] = _load_sales(cursor)
        payload["permits"] = _load_permits(cursor)
        payload["civic"] = _load_civic(cursor)
        payload["restaurants"] = _load_restaurants(cursor)

    payload["generated_at"] = timezone.now().isoformat()
    cache.set(SEDRO_WOOLLEY_PORTAL_CACHE_KEY, payload, SEDRO_WOOLLEY_PORTAL_CACHE_TTL_SECONDS)
    return payload
