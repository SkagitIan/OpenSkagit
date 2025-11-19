import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q

from openskagit.models import (
    Assessor,
    Sales,
    NeighborhoodProfile,
    NeighborhoodGeom,
)


def convert_decimals(obj):
    """
    Recursively convert Decimal instances to float for JSON storage.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj


class Command(BaseCommand):
    help = "Build complete neighborhood snapshot JSON for all neighborhoods (fast, aggregated)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hood",
            type=str,
            help="Optional: build profile for a single neighborhood code.",
        )

    # ==============================================================
    # MAIN HANDLE
    # ==============================================================

    def handle(self, *args, **options):
        only_hood = options.get("hood")

        # Neighborhood filter (your allowed groups)
        allowed = (
            Q(neighborhood_code__startswith="20B")
            | Q(neighborhood_code__startswith="21B")
            | Q(neighborhood_code__startswith="22B")
            | Q(neighborhood_code__startswith="23B")
            | Q(neighborhood_code__startswith="26B")
            | Q(neighborhood_code__startswith="27B")
            | Q(neighborhood_code__startswith="20LC")
            | Q(neighborhood_code__startswith="21LC")
            | Q(neighborhood_code__startswith="22LC")
            | Q(neighborhood_code__startswith="23LC")
            | Q(neighborhood_code__startswith="20CON")
            | Q(neighborhood_code__startswith="22CON")
            | Q(neighborhood_code__startswith="20A")
            | Q(neighborhood_code__startswith="21A")
            | Q(neighborhood_code__startswith="22A")
            | Q(neighborhood_code__startswith="23A")
            | Q(neighborhood_code__startswith="20FID")
            | Q(neighborhood_code__startswith="22FID")
            | Q(neighborhood_code__startswith="20GUEM")
            | Q(neighborhood_code__startswith="22GUEM")
            | Q(neighborhood_code__startswith="20SW")
            | Q(neighborhood_code__startswith="21SW")
            | Q(neighborhood_code__startswith="22SW")
            | Q(neighborhood_code__startswith="23SW")
            | Q(neighborhood_code__startswith="20CC")
            | Q(neighborhood_code__startswith="22CC")
            | Q(neighborhood_code__startswith="10CC")
            | Q(neighborhood_code__startswith="20MV")
            | Q(neighborhood_code__startswith="21MV")
            | Q(neighborhood_code__startswith="22MV")
            | Q(neighborhood_code__startswith="23MV")
        )

        # ----------------------------------------------------------
        # LOAD ALL PARCELS ONCE
        # ----------------------------------------------------------
        base_qs = (
            Assessor.objects.filter(allowed)
            .exclude(neighborhood_code__isnull=True)
            .exclude(neighborhood_code__exact="")
        )

        if only_hood:
            base_qs = base_qs.filter(neighborhood_code=only_hood)

        # Only pull fields we need for per-hood stats.
        parcel_rows = list(
            base_qs.values(
                "id",
                "parcel_number",
                "neighborhood_code",
                "neighborhood_code_description",
                "year_built",
                "living_area",
                "acres",
                "bathrooms",
                "finished_basement",
                "unfinished_basement",
                "garage_sqft",
                "building_style",
                "centroid_geog",
            )
        )

        if not parcel_rows:
            self.stdout.write(self.style.WARNING("No parcels found for allowed neighborhoods."))
            return

        # Maps
        hood_parcels = defaultdict(list)  # hood -> list of row dicts
        hood_by_id = {}  # parcel_id -> hood
        parcel_ids = []  # all parcel ids for spatial queries
        hoods_set = set()

        for row in parcel_rows:
            hood = row["neighborhood_code"]
            pid = row["id"]
            hood_parcels[hood].append(row)
            hood_by_id[pid] = hood
            parcel_ids.append(pid)
            hoods_set.add(hood)

        hoods = sorted(hoods_set)
        self.stdout.write(f"Found {len(hoods)} neighborhoods with parcels.")

        # Neighborhood geom names (one query)
        geom_name_map = dict(
            NeighborhoodGeom.objects.filter(code__in=hoods).values_list("code", "name")
        )

        # ----------------------------------------------------------
        # PRECOMPUTE GLOBAL SPATIAL + SALES STATISTICS
        # ----------------------------------------------------------
        self.stdout.write("Precomputing flood stats…")
        flood_stats = self.build_flood_stats(parcel_ids)

        self.stdout.write("Precomputing slope stats…")
        slope_stats = self.build_slope_stats(parcel_ids)

        self.stdout.write("Precomputing census stats…")
        census_stats = self.build_census_stats(parcel_ids)

        self.stdout.write("Precomputing amenity stats…")
        amenity_stats = self.build_amenity_stats(parcel_ids)

        self.stdout.write("Precomputing sales stats…")
        sale_stats = self.build_sale_stats(hoods)

        # ----------------------------------------------------------
        # BUILD PROFILES PER HOOD (PURE PYTHON)
        # ----------------------------------------------------------
        for hood in hoods:
            rows = hood_parcels[hood]
            if not rows:
                continue

            self.stdout.write(f"Processing hood {hood}…")

            json_blob = {}

            # BASIC COUNTS
            parcel_count = len(rows)
            json_blob["parcel_count"] = parcel_count

            # NEIGHBORHOOD NAME
            first_row = rows[0]
            nbhd_desc = first_row.get("neighborhood_code_description") or None
            json_blob["neighborhood_name"] = nbhd_desc or hood

            # geom name if available
            if hood in geom_name_map and geom_name_map[hood]:
                json_blob["geom_name"] = geom_name_map[hood]

            # YEAR BUILT / AGE BANDS
            years = [r["year_built"] for r in rows if r["year_built"] is not None]
            if years:
                json_blob["median_year_built"] = statistics.median(years)
                json_blob["oldest_year_built"] = min(years)
                json_blob["newest_year_built"] = max(years)
            else:
                json_blob["median_year_built"] = None
                json_blob["oldest_year_built"] = None
                json_blob["newest_year_built"] = None

            agebands = {"0_20": 0, "20_40": 0, "40_60": 0, "60_plus": 0}
            now_year = datetime.now().year
            for y in years:
                age = now_year - y
                if age <= 20:
                    agebands["0_20"] += 1
                elif age <= 40:
                    agebands["20_40"] += 1
                elif age <= 60:
                    agebands["40_60"] += 1
                else:
                    agebands["60_plus"] += 1
            json_blob["age_distribution"] = agebands

            # NEW BUILD COUNTS (hard-coded last 3 years)
            new_build_counts = {}
            for year in (2023, 2024, 2025):
                new_build_counts[str(year)] = sum(1 for r in rows if r["year_built"] == year)
            json_blob["new_builds"] = new_build_counts

            # LIVING AREA
            glas = [r["living_area"] for r in rows if r["living_area"] is not None]
            if glas:
                glas_sorted = sorted(glas)
                n = len(glas_sorted)
                json_blob["living_area_stats"] = {
                    "median": statistics.median(glas_sorted),
                    "p25": glas_sorted[n // 4],
                    "p75": glas_sorted[(3 * n) // 4],
                    "sample_size": n,
                }
            else:
                json_blob["living_area_stats"] = None

            # LOT SIZE (ACRES)
            acres = [r["acres"] for r in rows if r["acres"] is not None]
            if acres:
                acres_sorted = sorted(acres)
                n = len(acres_sorted)
                json_blob["lot_size"] = {
                    "median_acres": statistics.median(acres_sorted),
                    "p25": acres_sorted[n // 4],
                    "p75": acres_sorted[(3 * n) // 4],
                    "sample_size": n,
                }
            else:
                json_blob["lot_size"] = None

            # BATHROOMS
            baths = [r["bathrooms"] for r in rows if r["bathrooms"] is not None]
            if baths:
                baths_sorted = sorted(baths)
                median_baths = statistics.median(baths_sorted)
                distribution = []
                unique_vals = sorted(set(baths_sorted))
                for val in unique_vals:
                    count = sum(1 for b in baths_sorted if b == val)
                    label = f"{float(val):g} baths"
                    distribution.append(
                        {
                            "bathrooms": float(val),
                            "count": count,
                            "label": label,
                        }
                    )
                json_blob["bathrooms"] = {
                    "median": median_baths,
                    "distribution": distribution,
                    "sample_size": len(baths_sorted),
                }
            else:
                json_blob["bathrooms"] = {
                    "median": None,
                    "distribution": [],
                    "sample_size": 0,
                }

            # BASEMENT PCT
            finished_count = sum(
                1 for r in rows if r["finished_basement"] and r["finished_basement"] > 0
            )
            unfinished_count = sum(
                1 for r in rows if r["unfinished_basement"] and r["unfinished_basement"] > 0
            )
            total = parcel_count
            if total > 0:
                pct = round(((finished_count + unfinished_count) / total) * 100, 2)
            else:
                pct = None
            json_blob["basement_pct"] = pct

            # GARAGE
            garages = [r["garage_sqft"] for r in rows if r["garage_sqft"] is not None]
            json_blob["garage"] = {
                "median_sqft": statistics.median(garages) if garages else None,
                "sample_size": len(garages),
            }

            # BUILDING STYLE
            styles = [r["building_style"] for r in rows if r["building_style"]]
            if styles:
                total_styles = len(styles)
                counts = defaultdict(int)
                for st in styles:
                    counts[st] += 1

                style_summary = []
                for st in sorted(counts.keys()):
                    count = counts[st]
                    pct = round((count / total_styles) * 100, 2)
                    style_summary.append(
                        {
                            "style": st,
                            "count": count,
                            "percent": pct,
                        }
                    )
                json_blob["styles"] = {
                    "summary": style_summary,
                    "sample_size": total_styles,
                }
            else:
                json_blob["styles"] = {
                    "summary": [],
                    "sample_size": 0,
                }

            # FLOOD / SLOPE / CENSUS / AMENITIES / SALES (from precomputed maps)
            json_blob["flood_profile"] = flood_stats.get(hood, {})
            json_blob["slope_stats"] = slope_stats.get(hood, {})
            json_blob["census"] = census_stats.get(hood, {})
            json_blob["amenities"] = amenity_stats.get(hood, {})

            hood_sale_info = sale_stats.get(hood, {"sale_count": 0})
            json_blob["sales"] = hood_sale_info

            sale_count = hood_sale_info.get("sale_count", 0)
            if sale_count < 15:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {hood}: only {sale_count} sales (< 15 required)"
                    )
                )
                continue

            # SAVE PROFILE
            NeighborhoodProfile.objects.update_or_create(
                hood_id=hood,
                defaults={"json_data": convert_decimals(json_blob)},
            )

            self.stdout.write(self.style.SUCCESS(f"✓ Hood {hood} saved."))

        self.stdout.write("Done building neighborhood snapshots.")

    # ==============================================================
    # PRECOMPUTE HELPERS (GLOBAL QUERIES)
    # ==============================================================

    def build_flood_stats(self, parcel_ids):
        """
        Return dict[hood] -> { fld_zone: pct_of_parcels_in_that_zone }.
        Uses centroid_geog for intersect.
        """
        if not parcel_ids:
            return {}

        sql = """
        SELECT 
            a.neighborhood_code,
            f.fld_zone,
            COUNT(*) AS cnt
        FROM flood_skagit_fema AS f
        JOIN assessor AS a
          ON a.centroid_geog IS NOT NULL
         AND a.centroid_geog::geometry && f.geom
         AND ST_Intersects(a.centroid_geog::geometry, f.geom)
        WHERE a.id = ANY(%s)
        GROUP BY a.neighborhood_code, f.fld_zone;
        """

        hood_counts = defaultdict(lambda: defaultdict(int))

        with connection.cursor() as cur:
            cur.execute(sql, (parcel_ids,))
            for hood, fld_zone, cnt in cur.fetchall():
                if hood is None or fld_zone is None:
                    continue
                hood_counts[hood][fld_zone] += cnt

        result = {}
        for hood, zone_counts in hood_counts.items():
            total = sum(zone_counts.values()) or 1
            result[hood] = {
                zone: round((count / total) * 100, 2)
                for zone, count in zone_counts.items()
            }
        return result

    def build_slope_stats(self, parcel_ids):
        """
        Return dict[hood] -> {median, p75, count}.
        Uses dem_slope_tiles and centroid_geog for sampling.
        """
        if not parcel_ids:
            return {}

        sql = """
        SELECT 
            a.neighborhood_code,
            ST_Value(t.rast, a.centroid_geog::geometry) AS slope
        FROM dem_slope_tiles AS t
        JOIN assessor AS a
          ON a.centroid_geog IS NOT NULL
         AND ST_Intersects(t.rast, a.centroid_geog::geometry)
        WHERE a.id = ANY(%s);
        """

        hood_slopes = defaultdict(list)

        with connection.cursor() as cur:
            cur.execute(sql, (parcel_ids,))
            for hood, slope in cur.fetchall():
                if hood is None or slope is None:
                    continue
                hood_slopes[hood].append(float(slope))

        result = {}
        for hood, slopes in hood_slopes.items():
            if not slopes:
                continue
            slopes_sorted = sorted(slopes)
            n = len(slopes_sorted)
            result[hood] = {
                "median": statistics.median(slopes_sorted),
                "p75": slopes_sorted[int(n * 0.75)],
                "count": n,
            }
        return result

    def build_census_stats(self, parcel_ids):
        """
        Return dict[hood] -> census summary based on centroid_geog -> block group.
        """
        if not parcel_ids:
            return {}

        sql = """
        SELECT 
            a.neighborhood_code,
            acs.median_income,
            acs.population,
            acs.edu_bachelor,
            acs.edu_master,
            acs.edu_professional,
            acs.edu_doctorate
        FROM assessor AS a
        JOIN census.bg_skagit AS bg
          ON a.centroid_geog IS NOT NULL
         AND ST_Intersects(
                bg.geom,
                ST_Transform(a.centroid_geog::geometry, 2285)
             )
        JOIN census.acs_bg_skagit AS acs
          ON bg.geoid = acs.geoid
        WHERE a.id = ANY(%s);
        """

        hood_income = defaultdict(list)
        hood_pop = defaultdict(list)
        hood_bach = defaultdict(list)
        hood_mast = defaultdict(list)
        hood_prof = defaultdict(list)
        hood_doc = defaultdict(list)

        with connection.cursor() as cur:
            cur.execute(sql, (parcel_ids,))
            for (
                hood,
                median_income,
                population,
                edu_b,
                edu_m,
                edu_p,
                edu_d,
            ) in cur.fetchall():
                if hood is None:
                    continue
                if median_income is not None:
                    hood_income[hood].append(float(median_income))
                if population is not None:
                    hood_pop[hood].append(float(population))
                if edu_b is not None:
                    hood_bach[hood].append(float(edu_b))
                if edu_m is not None:
                    hood_mast[hood].append(float(edu_m))
                if edu_p is not None:
                    hood_prof[hood].append(float(edu_p))
                if edu_d is not None:
                    hood_doc[hood].append(float(edu_d))

        result = {}
        for hood in set(
            list(hood_income.keys())
            + list(hood_pop.keys())
            + list(hood_bach.keys())
            + list(hood_mast.keys())
            + list(hood_prof.keys())
            + list(hood_doc.keys())
        ):
            def med_or_none(arr):
                return statistics.median(arr) if arr else None

            result[hood] = {
                "median_income": med_or_none(hood_income.get(hood, [])),
                "median_population": med_or_none(hood_pop.get(hood, [])),
                "education": {
                    "bachelor": med_or_none(hood_bach.get(hood, [])),
                    "master": med_or_none(hood_mast.get(hood, [])),
                    "professional": med_or_none(hood_prof.get(hood, [])),
                    "doctorate": med_or_none(hood_doc.get(hood, [])),
                },
                "samples": len(hood_income.get(hood, []))
                or len(hood_pop.get(hood, []))
                or 0,
            }

        return result

    def build_amenity_stats(self, parcel_ids):
        """
        Return dict[hood] -> median distances to school / park / major road.
        Uses centroid_geog as geography.
        """
        if not parcel_ids:
            return {}

        def median_or_none(arr):
            return statistics.median(arr) if arr else None

        hood_school = defaultdict(list)
        hood_park = defaultdict(list)
        hood_road = defaultdict(list)

        # Schools
        sql_schools = """
        SELECT
            a.neighborhood_code,
            MIN(
                ST_Distance(
                    a.centroid_geog,
                    ST_Transform(s.geom, 4326)::geography
                )
            ) AS dist_m
        FROM assessor AS a
        JOIN osm.osm_schools AS s
        ON a.centroid_geog IS NOT NULL
        WHERE a.id = ANY(%s)
        GROUP BY a.neighborhood_code, a.id;

        """

        # Parks
        sql_parks = """
            SELECT
                a.neighborhood_code,
                MIN(
                    ST_Distance(
                        a.centroid_geog,
                        ST_Transform(p.geom, 4326)::geography
                    )
                ) AS dist_m
            FROM assessor AS a
            JOIN osm.osm_parks AS p
            ON a.centroid_geog IS NOT NULL
            WHERE a.id = ANY(%s)
            GROUP BY a.neighborhood_code, a.id;

        """

        # Major roads
        sql_roads = """
       SELECT
            a.neighborhood_code,
            MIN(
                ST_Distance(
                    a.centroid_geog,
                    ST_Transform(r.geom, 4326)::geography
                )
            ) AS dist_m
        FROM assessor AS a
        JOIN osm.osm_major_roads AS r
        ON a.centroid_geog IS NOT NULL
        WHERE a.id = ANY(%s)
        GROUP BY a.neighborhood_code, a.id;

        """

        with connection.cursor() as cur:
            # Schools
            cur.execute(sql_schools, (parcel_ids,))
            for hood, dist_m in cur.fetchall():
                if hood is None or dist_m is None:
                    continue
                hood_school[hood].append(float(dist_m))

            # Parks
            cur.execute(sql_parks, (parcel_ids,))
            for hood, dist_m in cur.fetchall():
                if hood is None or dist_m is None:
                    continue
                hood_park[hood].append(float(dist_m))

            # Roads
            cur.execute(sql_roads, (parcel_ids,))
            for hood, dist_m in cur.fetchall():
                if hood is None or dist_m is None:
                    continue
                hood_road[hood].append(float(dist_m))

        result = {}
        all_hoods = set(
            list(hood_school.keys())
            + list(hood_park.keys())
            + list(hood_road.keys())
        )

        for hood in all_hoods:
            result[hood] = {
                "dist_school_m": median_or_none(hood_school.get(hood, [])),
                "dist_park_m": median_or_none(hood_park.get(hood, [])),
                "dist_major_road_m": median_or_none(hood_road.get(hood, [])),
            }

        return result

    def build_sale_stats(self, hoods):
        """
        Return dict[hood] -> {"sale_count": int, "median_sale_price": float}.
        Uses last 2 years of sales and filters > 0.
        """
        if not hoods:
            return {}

        two_years_ago = datetime.now() - timedelta(days=730)

        sql = """
        SELECT 
            a.neighborhood_code,
            s.sale_price
        FROM sales AS s
        JOIN assessor AS a
          ON a.parcel_number = s.parcel_number
        WHERE a.neighborhood_code = ANY(%s)
          AND s.sale_price > 0
          AND s.sale_date >= %s;
        """

        hood_prices = defaultdict(list)

        with connection.cursor() as cur:
            cur.execute(sql, (hoods, two_years_ago))
            for hood, price in cur.fetchall():
                if hood is None or price is None:
                    continue
                hood_prices[hood].append(float(price))

        result = {}
        for hood, prices in hood_prices.items():
            if not prices:
                continue
            result[hood] = {
                "sale_count": len(prices),
                "median_sale_price": statistics.median(prices),
            }

        return result
