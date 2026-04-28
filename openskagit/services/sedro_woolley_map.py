import json
import logging
from collections import Counter
from typing import Any, Dict, List

from django.core.cache import cache
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


SEDRO_WOOLLEY_CITY_DISTRICT = "SEDRO WOOLLEY"
SEDRO_WOOLLEY_CITY_NAME = "Sedro-Woolley"
SEDRO_WOOLLEY_ZONING_LAYER_KEY = "sedro_woolley_parcel_zoning"
SEDRO_WOOLLEY_NEW_CONSTRUCTION_LAYER_KEY = "sedro_woolley_new_construction_2024_2025"
SEDRO_WOOLLEY_LAND_LIFT_LAYER_KEY = "sedro_woolley_land_lift"
SEDRO_WOOLLEY_CITY_WARDS_LAYER_KEY = "sedro_woolley_city_wards"
SEDRO_WOOLLEY_ZONING_CACHE_KEY = "openskagit:maps:sedro-woolley:zoning:v6"
SEDRO_WOOLLEY_ZONING_CACHE_TTL_SECONDS = 60 * 30
SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL = (
    "https://www.codepublishing.com/WA/SedroWoolley/html/SedroWoolley17/"
)
SEDRO_WOOLLEY_LAND_LIFT_TARGET_ZONES = ("R-15", "MC")
SEDRO_WOOLLEY_LAND_LIFT_BENCHMARK_QUANTILE = 0.80
SEDRO_WOOLLEY_LAND_LIFT_METHOD_VERSION = "v1-benchmark-per-acre-p80"

# Source of truth for descriptions is SWMC Title 17 chapter text:
# https://www.codepublishing.com/WA/SedroWoolley/html/SedroWoolley17/SedroWoolley17.html
SEDRO_WOOLLEY_ZONE_METADATA: Dict[str, Dict[str, Any]] = {
    "R-1": {
        "zone_name": "Residential 1 Environmentally Constrained",
        "description": (
            "Environmentally constrained residential areas near sensitive lands. "
            "Primarily one single-family home per lot with low-intensity agriculture and ADUs."
        ),
        "code_reference": "SWMC 17.06.005 and 17.06.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1706.html#17.06.005",
    },
    "R-5": {
        "zone_name": "Residential 5",
        "description": (
            "Lower-density neighborhood transition areas near rolling terrain and rural edges. "
            "Primarily single-family homes, low-intensity agriculture, and ADUs."
        ),
        "code_reference": "SWMC 17.08.005 and 17.08.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1708.html#17.08.005",
    },
    "R-7": {
        "zone_name": "Residential 7",
        "description": (
            "Traditional small-lot grid neighborhoods in older platted areas of the city. "
            "Primarily single-family homes with limited duplex opportunities."
        ),
        "code_reference": "SWMC 17.12.005 and 17.12.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1712.html#17.12.005",
    },
    "R-15": {
        "zone_name": "Residential 15",
        "description": (
            "Higher-density residential area intended to stay compatible with neighborhood scale. "
            "Allows multifamily housing, single-family homes, and selected service uses."
        ),
        "code_reference": "SWMC 17.16.005 and 17.16.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1716.html#17.16.005",
    },
    "MC": {
        "zone_name": "Mixed Commercial",
        "description": (
            "Mixed-use commercial corridors and nodes. Supports retail, services, light "
            "manufacturing, and residential units above first-floor commercial space."
        ),
        "code_reference": "SWMC 17.20.005 and 17.20.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1720.html#17.20.005",
    },
    "CBD": {
        "zone_name": "Central Business District",
        "description": (
            "Downtown walkable business core. Emphasizes commerce and offices with upper-floor "
            "or rear multifamily housing under district standards."
        ),
        "code_reference": "SWMC 17.24.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1724.html#17.24.010",
    },
    "I": {
        "zone_name": "Industrial",
        "description": (
            "Employment-focused industrial areas for manufacturing, warehousing, distribution, "
            "and offices with limited retail/service support uses."
        ),
        "code_reference": "SWMC 17.28.005 and 17.28.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1728.html#17.28.005",
    },
    "P": {
        "zone_name": "Public",
        "description": (
            "Publicly owned lands for parks, schools, infrastructure, and related institutional uses."
        ),
        "code_reference": "SWMC 17.32.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1732.html#17.32.010",
    },
    "OS": {
        "zone_name": "Open Space",
        "description": (
            "Open space lands for parks, recreation, agriculture, and very low-density residential use."
        ),
        "code_reference": "SWMC 17.34.010",
        "code_url": f"{SEDRO_WOOLLEY_CODE_CHAPTER_17_BASE_URL}SedroWoolley1734.html#17.34.010",
    },
    "URR": {
        "zone_name": "Urban Reserve Residential (County)",
        "description": (
            "County zoning code appears in parcel source data for a small number of edge parcels. "
            "This is not a Sedro-Woolley Title 17 city zoning chapter."
        ),
        "code_reference": "Check zoning_jurisdiction in parcel attributes",
    },
    "Unknown": {
        "zone_name": "Unknown / Unmapped",
        "description": (
            "No zoning code was available in parcel planning facts for this parcel."
        ),
        "code_reference": "Parcel planning facts missing zoning code",
    },
}


SEDRO_WOOLLEY_ZONING_SQL = """
    SELECT
        mp.parcel_number,
        mp.situs_address AS address,
        mp.proptype AS property_type,
        COALESCE(mp.final_year_built, mp.year_built, mp.eff_year_built)::int AS year_built,
        COALESCE(
            NULLIF(TRIM(ppf.zone_code), ''),
            NULLIF(TRIM(ppf.zoning_specific_class), ''),
            NULLIF(TRIM(ppf.zoning_general_class), ''),
            'Unknown'
        ) AS zone_code,
        COALESCE(NULLIF(TRIM(ppf.zoning_jurisdiction), ''), 'Sedro-Woolley') AS zoning_jurisdiction,
        mp.assessed_value::double precision AS assessed_value,
        mp.taxable_value::double precision AS taxable_value,
        COALESCE(mp.total_market_value, mp.assessed_value, mp.taxable_value)::double precision AS total_market_value,
        mp.building_value::double precision AS building_value,
        (COALESCE(mp.impr_land_value, 0) + COALESCE(mp.unimpr_land_value, 0))::double precision AS land_market_value,
        NULLIF(mp.acres, 0)::double precision AS acres,
        ST_AsGeoJSON(ST_Transform(pg.geom_2926, 4326), 5) AS geom_geojson
    FROM openskagit_parcelgeometry pg
    JOIN master_parcel mp
      ON mp.parcel_number = pg.parcel_id
    LEFT JOIN parcel_planning_facts ppf
      ON ppf.parcel_id = mp.parcel_number
    WHERE pg.geom_2926 IS NOT NULL
      AND UPPER(TRIM(COALESCE(mp.city_district, ''))) = %s
    ORDER BY mp.parcel_number
"""


SEDRO_WOOLLEY_NEW_CONSTRUCTION_SQL = """
    SELECT
        mp.parcel_number,
        mp.situs_address AS address,
        mp.proptype AS property_type,
        COALESCE(mp.final_year_built, mp.year_built, mp.eff_year_built)::int AS year_built,
        CASE
            WHEN mp.final_year_built IS NOT NULL THEN 'final_year_built'
            WHEN mp.year_built IS NOT NULL THEN 'year_built'
            WHEN mp.eff_year_built IS NOT NULL THEN 'eff_year_built'
            ELSE 'unknown'
        END AS year_source,
        ST_AsGeoJSON(ST_Transform(ST_PointOnSurface(pg.geom_2926), 4326), 6) AS point_geojson
    FROM master_parcel mp
    JOIN openskagit_parcelgeometry pg
      ON pg.parcel_id = mp.parcel_number
    WHERE pg.geom_2926 IS NOT NULL
      AND UPPER(TRIM(COALESCE(mp.city_district, ''))) = %s
      AND COALESCE(mp.final_year_built, mp.year_built, mp.eff_year_built) >= %s
    ORDER BY year_built DESC, mp.parcel_number
"""


SEDRO_WOOLLEY_LAND_LIFT_SQL = """
    WITH base AS (
        SELECT DISTINCT ON (mp.parcel_number)
            mp.parcel_number,
            mp.situs_address AS address,
            COALESCE(
                NULLIF(TRIM(ppf.zone_code), ''),
                NULLIF(TRIM(ppf.zoning_specific_class), ''),
                NULLIF(TRIM(ppf.zoning_general_class), ''),
                'Unknown'
            ) AS zone_code,
            COALESCE(NULLIF(TRIM(ppf.zoning_jurisdiction), ''), 'Sedro-Woolley') AS zoning_jurisdiction,
            mp.assessed_value::double precision AS assessed_value,
            mp.taxable_value::double precision AS taxable_value,
            COALESCE(mp.total_market_value, mp.assessed_value, mp.taxable_value)::double precision AS current_value,
            NULLIF(mp.acres, 0)::double precision AS acres,
            mp.building_value::double precision AS building_value,
            pg.geom_2926
        FROM master_parcel mp
        JOIN openskagit_parcelgeometry pg
          ON pg.parcel_id = mp.parcel_number
        LEFT JOIN parcel_planning_facts ppf
          ON ppf.parcel_id = mp.parcel_number
        WHERE pg.geom_2926 IS NOT NULL
          AND UPPER(TRIM(COALESCE(mp.city_district, ''))) = %s
        ORDER BY mp.parcel_number, ppf.zoning_last_verified DESC NULLS LAST
    ),
    zone_benchmarks AS (
        SELECT
            zone_code,
            percentile_cont(%s) WITHIN GROUP (ORDER BY current_value / acres) AS benchmark_value_per_acre
        FROM base
        WHERE zone_code = ANY(%s)
          AND current_value IS NOT NULL
          AND current_value > 0
          AND acres IS NOT NULL
          AND acres > 0
        GROUP BY zone_code
    ),
    lifted AS (
        SELECT
            b.parcel_number,
            b.address,
            b.zone_code,
            b.zoning_jurisdiction,
            b.assessed_value,
            b.taxable_value,
            b.current_value,
            b.acres,
            b.building_value,
            zb.benchmark_value_per_acre,
            (zb.benchmark_value_per_acre * b.acres) AS potential_value,
            GREATEST((zb.benchmark_value_per_acre * b.acres) - b.current_value, 0) AS lift_value,
            CASE
                WHEN b.current_value > 0 THEN GREATEST((zb.benchmark_value_per_acre * b.acres) - b.current_value, 0) / b.current_value
                ELSE NULL
            END AS lift_ratio,
            b.geom_2926
        FROM base b
        JOIN zone_benchmarks zb
          ON zb.zone_code = b.zone_code
        WHERE b.zone_code = ANY(%s)
          AND b.current_value IS NOT NULL
          AND b.current_value > 0
          AND b.acres IS NOT NULL
          AND b.acres > 0
    ),
    scored AS (
        SELECT
            parcel_number,
            address,
            zone_code,
            zoning_jurisdiction,
            assessed_value,
            taxable_value,
            current_value,
            acres,
            building_value,
            benchmark_value_per_acre,
            potential_value,
            lift_value,
            lift_ratio,
            ROUND((PERCENT_RANK() OVER (ORDER BY lift_value) * 100)::numeric, 2) AS lift_score,
            ST_AsGeoJSON(ST_Transform(geom_2926, 4326), 5) AS geom_geojson
        FROM lifted
    )
    SELECT
        parcel_number,
        address,
        zone_code,
        zoning_jurisdiction,
        assessed_value,
        taxable_value,
        current_value,
        acres,
        building_value,
        benchmark_value_per_acre,
        potential_value,
        lift_value,
        lift_ratio,
        lift_score,
        geom_geojson
    FROM scored
    ORDER BY lift_value DESC, parcel_number
"""

SEDRO_WOOLLEY_CITY_WARDS_SQL = """
    WITH sw_wards AS (
        SELECT
            "OBJECTID"::bigint AS object_id,
            NULLIF(TRIM("WARD"), '') AS ward_code,
            NULLIF(TRIM("PHOTO"), '') AS photo_url,
            NULLIF(TRIM("WEBSITE"), '') AS website_url,
            "GlobalID" AS global_id,
            geometry AS ward_geom
        FROM reference_city_wards
        WHERE geometry IS NOT NULL
          AND UPPER(TRIM(COALESCE("WARD", ''))) LIKE 'SW%%'
    ),
    latest_turnout_year AS (
        SELECT MAX(election_year)::int AS election_year
        FROM precinct_participation_index
    ),
    latest_census_year AS (
        SELECT MAX(year)::int AS census_year
        FROM reference_census_acs
    )
    SELECT
        w.object_id,
        w.ward_code,
        w.photo_url,
        w.website_url,
        w.global_id,
        turnout_year.election_year AS turnout_year,
        COALESCE(turnout_stats.ballots_cast, 0)::numeric(16, 2) AS turnout_ballots_cast,
        COALESCE(turnout_stats.residential_parcels, 0)::numeric(16, 2) AS turnout_residential_parcels,
        CASE
            WHEN COALESCE(turnout_stats.residential_parcels, 0) > 0
                THEN ROUND((turnout_stats.ballots_cast / turnout_stats.residential_parcels)::numeric, 6)
            ELSE NULL
        END AS turnout_rate,
        census_year.census_year,
        COALESCE(pop_stats.population_estimate, 0)::numeric(16, 2) AS population_estimate,
        COALESCE(parcel_stats.parcel_count, 0)::bigint AS parcel_count,
        COALESCE(parcel_stats.total_market_value, 0)::numeric(18, 2) AS total_market_value,
        ST_AsGeoJSON(ST_Transform(w.ward_geom, 4326), 6) AS geom_geojson
    FROM sw_wards w
    CROSS JOIN latest_turnout_year turnout_year
    CROSS JOIN latest_census_year census_year
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS parcel_count,
            SUM(COALESCE(mp.total_market_value, mp.assessed_value, mp.taxable_value, 0)::double precision) AS total_market_value
        FROM openskagit_parcelgeometry pg
        JOIN master_parcel mp
          ON mp.parcel_number = pg.parcel_id
        WHERE pg.geom_2926 IS NOT NULL
          AND UPPER(TRIM(COALESCE(mp.city_district, ''))) = %s
          AND ST_Intersects(
              COALESCE(pg.centroid_2926, ST_PointOnSurface(pg.geom_2926)),
              w.ward_geom
          )
    ) parcel_stats ON TRUE
    LEFT JOIN LATERAL (
        WITH precinct_overlap AS (
            SELECT
                ppi.ballots_cast::double precision AS ballots_cast,
                ppi.residential_parcels::double precision AS residential_parcels,
                CASE
                    WHEN ST_Area(vp.geom_2926) > 0 THEN
                        GREATEST(
                            ST_Area(
                                ST_Intersection(
                                    ST_MakeValid(vp.geom_2926),
                                    ST_MakeValid(w.ward_geom)
                                )
                            ),
                            0
                        ) / ST_Area(vp.geom_2926)
                    ELSE 0
                END AS overlap_ratio
            FROM precinct_participation_index ppi
            JOIN reference_votingprecinct vp
              ON vp.prec_code = ppi.prec_code
            WHERE ppi.election_year = turnout_year.election_year
              AND vp.county_name = 'Skagit'
              AND ST_Intersects(vp.geom_2926, w.ward_geom)
        )
        SELECT
            SUM(ballots_cast * overlap_ratio) AS ballots_cast,
            SUM(residential_parcels * overlap_ratio) AS residential_parcels
        FROM precinct_overlap
    ) turnout_stats ON TRUE
    LEFT JOIN LATERAL (
        WITH bg_overlap AS (
            SELECT
                acs.population::double precision AS population,
                CASE
                    WHEN ST_Area(cbg.geometry) > 0 THEN
                        GREATEST(
                            ST_Area(
                                ST_Intersection(
                                    ST_MakeValid(cbg.geometry),
                                    ST_MakeValid(w.ward_geom)
                                )
                            ),
                            0
                        ) / ST_Area(cbg.geometry)
                    ELSE 0
                END AS overlap_ratio
            FROM reference_census_block_groups cbg
            JOIN reference_census_acs acs
              ON acs.geoid = cbg.geoid
             AND acs.year = census_year.census_year
            WHERE ST_Intersects(cbg.geometry, w.ward_geom)
        )
        SELECT
            SUM(population * overlap_ratio) AS population_estimate
        FROM bg_overlap
    ) pop_stats ON TRUE
    ORDER BY w.ward_code
"""


def _dictfetchall(cursor) -> List[Dict[str, Any]]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_zone_legend_entry(*, zone_code: str, parcel_count: int) -> Dict[str, Any]:
    zone_meta = SEDRO_WOOLLEY_ZONE_METADATA.get(zone_code, {})
    return {
        "zone_code": zone_code,
        "zone_name": zone_meta.get("zone_name", zone_code),
        "description": zone_meta.get(
            "description",
            "No Sedro-Woolley zoning description is currently mapped for this code.",
        ),
        "code_reference": zone_meta.get("code_reference"),
        "code_url": zone_meta.get("code_url"),
        "parcel_count": parcel_count,
    }


def _land_lift_band(score: float) -> str:
    if score >= 80:
        return "Very High"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Moderate"
    if score >= 20:
        return "Low"
    return "Very Low"


def load_sedro_woolley_zoning_feature_collection(*, force_refresh: bool = False) -> Dict[str, Any]:
    if not force_refresh:
        cached = cache.get(SEDRO_WOOLLEY_ZONING_CACHE_KEY)
        if isinstance(cached, dict):
            return cached

    with connection.cursor() as cursor:
        cursor.execute(SEDRO_WOOLLEY_ZONING_SQL, [SEDRO_WOOLLEY_CITY_DISTRICT])
        rows = _dictfetchall(cursor)

    features: List[Dict[str, Any]] = []
    zone_counts: Counter[str] = Counter()

    for row in rows:
        geometry_raw = row.pop("geom_geojson", None)
        if not geometry_raw:
            continue
        try:
            geometry = json.loads(geometry_raw)
        except json.JSONDecodeError:
            logger.warning("Skipping parcel zoning row with invalid geometry.")
            continue
        zone_code = (row.get("zone_code") or "").strip() or "Unknown"
        row["zone_code"] = zone_code
        for field in (
            "assessed_value",
            "taxable_value",
            "total_market_value",
            "building_value",
            "land_market_value",
        ):
            numeric_value = _to_float(row.get(field))
            row[field] = round(numeric_value, 2) if numeric_value is not None else None
        acres = _to_float(row.get("acres"))
        row["acres"] = round(acres, 6) if acres is not None else None
        assessed_value = _to_float(row.get("assessed_value"))
        building_value = _to_float(row.get("building_value"))
        if assessed_value and assessed_value > 0 and building_value is not None:
            row["improvement_share"] = round(building_value / assessed_value, 4)
        else:
            row["improvement_share"] = None
        zone_counts[zone_code] += 1
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": row,
            }
        )

    legend = [
        _build_zone_legend_entry(zone_code=zone_code, parcel_count=parcel_count)
        for zone_code, parcel_count in sorted(zone_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    payload: Dict[str, Any] = {
        "type": "FeatureCollection",
        "layer": SEDRO_WOOLLEY_ZONING_LAYER_KEY,
        "layer_label": "Sedro-Woolley parcel zoning",
        "city": SEDRO_WOOLLEY_CITY_NAME,
        "filters": {"city_district": SEDRO_WOOLLEY_CITY_DISTRICT},
        "generated_at": timezone.now().isoformat(),
        "feature_count": len(features),
        "legend": legend,
        "features": features,
    }

    min_new_construction_year = timezone.now().year - 2
    with connection.cursor() as cursor:
        cursor.execute(
            SEDRO_WOOLLEY_NEW_CONSTRUCTION_SQL,
            [SEDRO_WOOLLEY_CITY_DISTRICT, min_new_construction_year],
        )
        new_construction_rows = _dictfetchall(cursor)

    new_construction_features: List[Dict[str, Any]] = []
    new_construction_year_counts: Counter[int] = Counter()
    for row in new_construction_rows:
        geometry_raw = row.pop("point_geojson", None)
        if not geometry_raw:
            continue
        try:
            geometry = json.loads(geometry_raw)
        except json.JSONDecodeError:
            logger.warning("Skipping new construction row with invalid geometry.")
            continue
        built_year = int(row.get("year_built") or 0)
        if built_year >= min_new_construction_year:
            new_construction_year_counts[built_year] += 1
        new_construction_features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": row,
            }
        )

    payload["new_construction"] = {
        "type": "FeatureCollection",
        "layer": SEDRO_WOOLLEY_NEW_CONSTRUCTION_LAYER_KEY,
        "layer_label": "New homes (last 24 months)",
        "city": SEDRO_WOOLLEY_CITY_NAME,
        "feature_count": len(new_construction_features),
        "min_year": min_new_construction_year,
        "years": sorted(new_construction_year_counts.keys()),
        "summary_by_year": [
            {"year": year, "parcel_count": parcel_count}
            for year, parcel_count in sorted(new_construction_year_counts.items(), key=lambda item: item[0])
        ],
        "summary": {
            "2024": new_construction_year_counts.get(2024, 0),
            "2025": new_construction_year_counts.get(2025, 0),
            "total": len(new_construction_features),
        },
        "features": new_construction_features,
    }

    city_ward_rows: List[Dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(SEDRO_WOOLLEY_CITY_WARDS_SQL, [SEDRO_WOOLLEY_CITY_DISTRICT])
            city_ward_rows = _dictfetchall(cursor)
    except Exception:
        logger.warning("Sedro-Woolley city wards layer unavailable from reference_city_wards.", exc_info=True)

    city_ward_features: List[Dict[str, Any]] = []
    ward_codes: List[str] = []
    for row in city_ward_rows:
        geometry_raw = row.pop("geom_geojson", None)
        if not geometry_raw:
            continue
        try:
            geometry = json.loads(geometry_raw)
        except json.JSONDecodeError:
            logger.warning("Skipping city ward row with invalid geometry.")
            continue
        ward_code = (row.get("ward_code") or "").strip()
        if ward_code:
            ward_codes.append(ward_code)
        city_ward_features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": row,
            }
        )

    payload["city_wards"] = {
        "type": "FeatureCollection",
        "layer": SEDRO_WOOLLEY_CITY_WARDS_LAYER_KEY,
        "layer_label": "Sedro-Woolley city wards",
        "city": SEDRO_WOOLLEY_CITY_NAME,
        "feature_count": len(city_ward_features),
        "ward_codes": sorted(set(ward_codes)),
        "features": city_ward_features,
    }

    with connection.cursor() as cursor:
        cursor.execute(
            SEDRO_WOOLLEY_LAND_LIFT_SQL,
            [
                SEDRO_WOOLLEY_CITY_DISTRICT,
                SEDRO_WOOLLEY_LAND_LIFT_BENCHMARK_QUANTILE,
                list(SEDRO_WOOLLEY_LAND_LIFT_TARGET_ZONES),
                list(SEDRO_WOOLLEY_LAND_LIFT_TARGET_ZONES),
            ],
        )
        land_lift_rows = _dictfetchall(cursor)

    land_lift_features: List[Dict[str, Any]] = []
    land_lift_band_counts: Counter[str] = Counter()
    land_lift_zone_counts: Counter[str] = Counter()
    zone_benchmarks: Dict[str, float] = {}
    max_lift_value = 0.0
    top_decile_count = 0

    for row in land_lift_rows:
        geometry_raw = row.pop("geom_geojson", None)
        if not geometry_raw:
            continue
        try:
            geometry = json.loads(geometry_raw)
        except json.JSONDecodeError:
            logger.warning("Skipping land lift row with invalid geometry.")
            continue

        zone_code = (row.get("zone_code") or "").strip() or "Unknown"
        current_value = float(row.get("current_value") or 0.0)
        assessed_value = _to_float(row.get("assessed_value"))
        taxable_value = _to_float(row.get("taxable_value"))
        potential_value = float(row.get("potential_value") or 0.0)
        lift_value = float(row.get("lift_value") or 0.0)
        lift_ratio = float(row.get("lift_ratio") or 0.0)
        lift_score = float(row.get("lift_score") or 0.0)
        acres = float(row.get("acres") or 0.0)
        benchmark_per_acre = float(row.get("benchmark_value_per_acre") or 0.0)
        building_value = float(row.get("building_value") or 0.0)
        improvement_share = (building_value / current_value) if current_value > 0 else None
        lift_band = _land_lift_band(lift_score)

        row["zone_code"] = zone_code
        row["assessed_value"] = round(assessed_value, 2) if assessed_value is not None else None
        row["taxable_value"] = round(taxable_value, 2) if taxable_value is not None else None
        row["current_value"] = round(current_value, 2)
        row["potential_value"] = round(potential_value, 2)
        row["lift_value"] = round(lift_value, 2)
        row["lift_ratio"] = round(lift_ratio, 4)
        row["lift_score"] = round(lift_score, 2)
        row["acres"] = round(acres, 6)
        row["benchmark_value_per_acre"] = round(benchmark_per_acre, 2)
        row["building_value"] = round(building_value, 2)
        row["improvement_share"] = round(improvement_share, 4) if improvement_share is not None else None
        row["lift_band"] = lift_band

        zone_meta = SEDRO_WOOLLEY_ZONE_METADATA.get(zone_code, {})
        row["zone_name"] = zone_meta.get("zone_name", zone_code)

        land_lift_band_counts[lift_band] += 1
        land_lift_zone_counts[zone_code] += 1
        if benchmark_per_acre > 0 and zone_code not in zone_benchmarks:
            zone_benchmarks[zone_code] = benchmark_per_acre
        max_lift_value = max(max_lift_value, lift_value)
        if lift_score >= 90:
            top_decile_count += 1

        land_lift_features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": row,
            }
        )

    lift_bins = [
        {"label": "Very High (80-100)", "min_score": 80, "max_score": 100, "color": "#7f1d1d"},
        {"label": "High (60-79)", "min_score": 60, "max_score": 79.99, "color": "#b91c1c"},
        {"label": "Moderate (40-59)", "min_score": 40, "max_score": 59.99, "color": "#ea580c"},
        {"label": "Low (20-39)", "min_score": 20, "max_score": 39.99, "color": "#f59e0b"},
        {"label": "Very Low (0-19)", "min_score": 0, "max_score": 19.99, "color": "#facc15"},
    ]
    for entry in lift_bins:
        min_score = float(entry["min_score"])
        max_score = float(entry["max_score"])
        entry["parcel_count"] = sum(
            1
            for feature in land_lift_features
            if min_score <= float(feature["properties"].get("lift_score") or 0) <= max_score
        )

    payload["land_lift"] = {
        "type": "FeatureCollection",
        "layer": SEDRO_WOOLLEY_LAND_LIFT_LAYER_KEY,
        "layer_label": "Land Lift (R-15 and MC)",
        "city": SEDRO_WOOLLEY_CITY_NAME,
        "target_zones": list(SEDRO_WOOLLEY_LAND_LIFT_TARGET_ZONES),
        "feature_count": len(land_lift_features),
        "score_bins": lift_bins,
        "summary": {
            "total_candidates": len(land_lift_features),
            "top_decile_count": top_decile_count,
            "max_lift_value": round(max_lift_value, 2),
            "band_counts": dict(land_lift_band_counts),
            "zone_counts": dict(land_lift_zone_counts),
            "zone_benchmark_value_per_acre": {
                zone: round(value, 2) for zone, value in sorted(zone_benchmarks.items())
            },
        },
        "methodology": {
            "version": SEDRO_WOOLLEY_LAND_LIFT_METHOD_VERSION,
            "current_value_field": "COALESCE(master_parcel.total_market_value, master_parcel.assessed_value, master_parcel.taxable_value)",
            "potential_value_formula": "zone_benchmark_value_per_acre * acres",
            "zone_benchmark_definition": f"Percentile {int(SEDRO_WOOLLEY_LAND_LIFT_BENCHMARK_QUANTILE * 100)} of current value-per-acre for each target zone",
            "lift_formula": "max(potential_value - current_value, 0)",
            "score_definition": "Percent rank of lift value among target-zone parcels, scaled 0-100",
            "score_interpretation": (
                "Lift score is relative ranking among R-15 and MC candidates. "
                "A score of 72 means this parcel has a larger modeled lift gap than about 72% of candidates."
            ),
            "not_a_prediction": (
                "Higher score indicates larger relative gap in this benchmark model; "
                "it is not a guaranteed outcome and not a good/bad label."
            ),
            "source": "master_parcel + parcel_planning_facts + openskagit_parcelgeometry",
        },
        "features": land_lift_features,
    }

    cache.set(SEDRO_WOOLLEY_ZONING_CACHE_KEY, payload, SEDRO_WOOLLEY_ZONING_CACHE_TTL_SECONDS)
    return payload
