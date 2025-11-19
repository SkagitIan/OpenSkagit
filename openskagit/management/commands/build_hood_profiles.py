import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q
# Ensure these match your actual app name
from openskagit.models import Assessor, NeighborhoodProfile, Sales 

def convert_decimals(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj

class Command(BaseCommand):
    help = "High-performance builder for neighborhood snapshot JSON."

    def add_arguments(self, parser):
        parser.add_argument("--hood", type=str, help="Process a specific neighborhood code.")

    def handle(self, *args, **options):
        start_time = datetime.now()
        
        # ---------------------------------------------------------
        # 1. DEFINE SCOPE
        # ---------------------------------------------------------
        # (Truncated your filter list for brevity, but logic applies to all)
        filters = (
            Q(neighborhood_code__startswith="20B") | Q(neighborhood_code__startswith="21B") |
            Q(neighborhood_code__startswith="22B") | Q(neighborhood_code__startswith="23B") |
            Q(neighborhood_code__startswith="26B") | Q(neighborhood_code__startswith="27B") |
            Q(neighborhood_code__startswith="20LC") | Q(neighborhood_code__startswith="21LC") |
            Q(neighborhood_code__startswith="22LC") | Q(neighborhood_code__startswith="23LC") |
            Q(neighborhood_code__startswith="20CON") | Q(neighborhood_code__startswith="22CON") |
            Q(neighborhood_code__startswith="20A") | Q(neighborhood_code__startswith="21A") |
            Q(neighborhood_code__startswith="22A") | Q(neighborhood_code__startswith="23A") |
            Q(neighborhood_code__startswith="20FID") | Q(neighborhood_code__startswith="22FID") |
            Q(neighborhood_code__startswith="20GUEM") | Q(neighborhood_code__startswith="22GUEM") |
            Q(neighborhood_code__startswith="20SW") | Q(neighborhood_code__startswith="21SW") |
            Q(neighborhood_code__startswith="22SW") | Q(neighborhood_code__startswith="23SW") |
            Q(neighborhood_code__startswith="20CC") | Q(neighborhood_code__startswith="22CC") |
            Q(neighborhood_code__startswith="10CC") | Q(neighborhood_code__startswith="20MV") |
            Q(neighborhood_code__startswith="21MV") | Q(neighborhood_code__startswith="22MV") |
            Q(neighborhood_code__startswith="23MV")
        )

        if options["hood"]:
            filters = Q(neighborhood_code=options["hood"])

        valid_hoods = list(
            Assessor.objects.filter(filters)
            .exclude(neighborhood_code__isnull=True)
            .exclude(neighborhood_code__exact="")
            .values_list("neighborhood_code", flat=True)
            .distinct()
        )

        if not valid_hoods:
            self.stdout.write(self.style.WARNING("No neighborhoods found matching criteria."))
            return

        self.stdout.write(f"Processing {len(valid_hoods)} neighborhoods...")

        # ---------------------------------------------------------
        # 2. FETCH AGGREGATED STATISTICS
        # ---------------------------------------------------------
        
        self.stdout.write("  - Aggregating main structural stats (inc. Taxes)...")
        main_stats = self.get_main_parcel_stats(valid_hoods)

        self.stdout.write("  - Aggregating distributions (Bed/Bath/Style)...")
        bath_dist = self.get_distribution(valid_hoods, "bathrooms")
        bed_dist = self.get_distribution(valid_hoods, "bedrooms")
        style_dist = self.get_distribution(valid_hoods, "building_style")

        self.stdout.write("  - Aggregating sales history (2020-2025)...")
        sales_history = self.get_sales_history(valid_hoods)

        self.stdout.write("  - Calculating spatial stats...")
        flood_stats = self.get_flood_stats(valid_hoods)
        slope_stats = self.get_slope_stats(valid_hoods)
        census_stats = self.get_census_stats(valid_hoods)
        amenity_stats = self.get_amenity_stats_optimized(valid_hoods)
        
        # ---------------------------------------------------------
        # 3. ASSEMBLE AND SAVE
        # ---------------------------------------------------------
        self.stdout.write("  - Assembling JSON...")
        profiles_to_upsert = []
        
        for hood in valid_hoods:
            if hood not in main_stats:
                continue
                
            base = main_stats[hood]
            hood_sales_hist = sales_history.get(hood, {})
            
            # Get current year (2024/2025) sales for the summary block
            # We use the history dict to get the most recent relevant data
            current_year = str(datetime.now().year)
            last_year = str(datetime.now().year - 1)
            
            # Fallback: if 2025 is empty, look at 2024 for summary stats
            recent_sale_data = hood_sales_hist.get(current_year)
            if not recent_sale_data or recent_sale_data['count'] == 0:
                 recent_sale_data = hood_sales_hist.get(last_year, {"count": 0, "median_price": None})

            # Calculate Total Historical Sales for the filter (Safety Check)
            total_recorded_sales = sum(d['count'] for d in hood_sales_hist.values())
            
            if total_recorded_sales < 10:
                # self.stdout.write(f"Skipping {hood} (Low Sales Volume)")
                continue

            # Calculate Turnover Rate (Sales in last 12 months / Total Parcels)
            # We'll roughly use last year's count for this metric
            last_year_sales = hood_sales_hist.get(last_year, {}).get('count', 0)
            turnover_rate = round((last_year_sales / base["count"]) * 100, 2) if base["count"] > 0 else 0

            json_blob = {
                "neighborhood_name": base.get("desc") or hood,
                "parcel_count": base["count"],
                "turnover_rate": turnover_rate,
                
                # --- AGE ---
                "median_year_built": base["med_year"],
                "oldest_year_built": base["min_year"],
                "newest_year_built": base["max_year"],
                "age_distribution": {
                    "0_20": base["age_0_20"],
                    "20_40": base["age_20_40"],
                    "40_60": base["age_40_60"],
                    "60_plus": base["age_60_plus"],
                },
                "new_builds": {
                    "2023": base["built_2023"],
                    "2024": base["built_2024"],
                    "2025": base["built_2025"],
                },

                # --- STRUCTURE ---
                "living_area_stats": {
                    "median": base["med_sqft"],
                    "p25": base["sqft_p25"],
                    "p75": base["sqft_p75"],
                    "sample_size": base["cnt_sqft"]
                },
                "lot_size": {
                    "median_acres": base["med_acres"],
                    "p25": base["acres_p25"],
                    "p75": base["acres_p75"],
                    "sample_size": base["cnt_acres"]
                },
                "garage": {
                    "median_sqft": base["med_garage"],
                    "sample_size": base["cnt_garage"]
                },
                "basement_pct": base["pct_basement"],

                # --- ROOMS ---
                "bathrooms": {
                    "median": base["med_bath"],
                    "sample_size": base["cnt_bath"],
                    "distribution": bath_dist.get(hood, [])
                },
                "bedrooms": {
                    "median": base["med_bed"],
                    "sample_size": base["cnt_bed"],
                    "distribution": bed_dist.get(hood, [])
                },
                "styles": {
                    "sample_size": base["cnt_style"],
                    "summary": style_dist.get(hood, [])
                },

                # --- FINANCIALS ---
                "tax_stats": {
                    "median_tax_amount": base["med_tax"],
                    "median_assessed_value": base["med_assessed"],
                    # Effective Tax Rate = Tax / Assessed Value
                    "effective_tax_rate": round((base["med_tax"] / base["med_assessed"] * 100), 2) if base["med_assessed"] and base["med_tax"] else None
                },
                "sales_summary": {
                    "median_price": recent_sale_data.get("median_price"),
                    "median_ppsf": recent_sale_data.get("median_ppsf"),
                    "last_year_sales_count": recent_sale_data.get("count")
                },
                "sales_history": hood_sales_hist,

                # --- SPATIAL ---
                "flood_profile": flood_stats.get(hood, {}),
                #"slope_stats": slope_stats.get(hood, {}),
                "census": census_stats.get(hood, {}),
                "amenities": amenity_stats.get(hood, {})
            }

            profiles_to_upsert.append(
                NeighborhoodProfile(
                    hood_id=hood,
                    json_data=convert_decimals(json_blob)
                )
            )

        self.stdout.write(f"  - Saving {len(profiles_to_upsert)} profiles...")
        
        NeighborhoodProfile.objects.bulk_create(
            profiles_to_upsert,
            update_conflicts=True,
            unique_fields=['hood_id'],
            update_fields=['json_data']
        )

        duration = datetime.now() - start_time
        self.stdout.write(self.style.SUCCESS(f"Done! Processed in {duration}."))

    # ==========================================================================
    # SQL HELPERS
    # ==========================================================================

    def get_main_parcel_stats(self, hoods):
        now_year = datetime.now().year
        
        # NOTE: We use REGEXP_REPLACE to clean total_taxes (e.g., "$3,400.00" -> "3400.00")
        
        sql = f"""
        SELECT
            neighborhood_code,
            MAX(neighborhood_code_description) as desc,
            COUNT(*) as count,
            
            -- Year Built
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY year_built) as med_year,
            MIN(year_built) as min_year,
            MAX(year_built) as max_year,
            
            -- Age Buckets
            COUNT(*) FILTER (WHERE ({now_year} - year_built) <= 20) as age_0_20,
            COUNT(*) FILTER (WHERE ({now_year} - year_built) BETWEEN 21 AND 40) as age_20_40,
            COUNT(*) FILTER (WHERE ({now_year} - year_built) BETWEEN 41 AND 60) as age_40_60,
            COUNT(*) FILTER (WHERE ({now_year} - year_built) > 60) as age_60_plus,
            
            -- Recent Builds
            COUNT(*) FILTER (WHERE year_built = 2023) as built_2023,
            COUNT(*) FILTER (WHERE year_built = 2024) as built_2024,
            COUNT(*) FILTER (WHERE year_built = 2025) as built_2025,

            -- Size
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY living_area) as med_sqft,
            PERCENTILE_CONT(0.25) WITHIN GROUP(ORDER BY living_area) as sqft_p25,
            PERCENTILE_CONT(0.75) WITHIN GROUP(ORDER BY living_area) as sqft_p75,
            COUNT(living_area) as cnt_sqft,

            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acres) as med_acres,
            PERCENTILE_CONT(0.25) WITHIN GROUP(ORDER BY acres) as acres_p25,
            PERCENTILE_CONT(0.75) WITHIN GROUP(ORDER BY acres) as acres_p75,
            COUNT(acres) as cnt_acres,

            -- Rooms / Garage
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY bathrooms) as med_bath,
            COUNT(bathrooms) as cnt_bath,
            
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY bedrooms) as med_bed,
            COUNT(bedrooms) as cnt_bed,
            
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY garage_sqft) as med_garage,
            COUNT(garage_sqft) as cnt_garage,
            
            -- Financials (Cleaning Text Fields)
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY assessed_value) as med_assessed,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY 
                CAST(NULLIF(REGEXP_REPLACE(total_taxes, '[^0-9.]', '', 'g'), '') AS NUMERIC)
            ) as med_tax,
            
            -- Basement
            SUM(CASE WHEN finished_basement > 0 OR unfinished_basement > 0 THEN 1 ELSE 0 END) as basement_count,
            
            -- Style
            COUNT(building_style) as cnt_style

        FROM assessor
        WHERE neighborhood_code = ANY(%s)
        GROUP BY neighborhood_code
        """
        
        results = {}
        with connection.cursor() as cur:
            cur.execute(sql, (hoods,))
            cols = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                data = dict(zip(cols, row))
                total = data['count']
                bsmt = data.pop('basement_count') or 0
                data['pct_basement'] = round((bsmt / total) * 100, 2) if total else 0
                results[data['neighborhood_code']] = data
        return results

    def get_distribution(self, hoods, field_name):
        """
        Generic grouper. Works for 'bathrooms', 'bedrooms', 'building_style'.
        """
        sql = f"""
        SELECT 
            neighborhood_code, 
            {field_name} as val, 
            COUNT(*) as cnt
        FROM assessor
        WHERE neighborhood_code = ANY(%s) AND {field_name} IS NOT NULL
        GROUP BY neighborhood_code, {field_name}
        ORDER BY neighborhood_code, {field_name}
        """
        
        totals = defaultdict(int)
        temp_data = defaultdict(list)
        
        with connection.cursor() as cur:
            cur.execute(sql, (hoods,))
            for hood, val, cnt in cur.fetchall():
                totals[hood] += cnt
                
                # Formatting label based on field type
                if field_name in ['bathrooms', 'bedrooms']:
                    label = f"{val:g} {field_name}"
                    key = field_name
                else:
                    label = str(val)
                    key = "style"
                
                temp_data[hood].append({
                    key: float(val) if field_name in ['bathrooms', 'bedrooms'] else val,
                    "count": cnt,
                    "label": label
                })

        results = {}
        for hood, items in temp_data.items():
            total = totals[hood]
            final_list = []
            for item in items:
                item['percent'] = round((item['count'] / total) * 100, 2) if total else 0
                final_list.append(item)
            results[hood] = final_list
            
        return results

    def get_sales_history(self, hoods):
        """
        Groups sales by year (2020-2025).
        Joins Sales -> Assessor to calculate PPSF (Price / Living Area).
        """
        start_year = 2020
        start_date = datetime(start_year, 1, 1)

        sql = """
        SELECT 
            a.neighborhood_code,
            EXTRACT(YEAR FROM s.sale_date)::int as sale_year,
            COUNT(*) as sale_count,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY s.sale_price) as med_price,
            -- PPSF Calculation: Price / Living Area (Null if area is 0 or null)
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY (s.sale_price / NULLIF(a.living_area, 0))) as med_ppsf
        FROM sales s
        JOIN assessor a ON a.parcel_number = s.parcel_number
        WHERE a.neighborhood_code = ANY(%s)
          AND s.sale_price > 0
          AND s.sale_date >= %s
          AND a.living_area > 0 
          AND s.deed_type IN ('WARRANTY DEED', 'STATUTORY WARRANTY DEED')
        GROUP BY a.neighborhood_code, sale_year
        ORDER BY a.neighborhood_code, sale_year DESC
        """

        results = defaultdict(dict)
        with connection.cursor() as cur:
            cur.execute(sql, (hoods, start_date))
            for hood, year, count, price, ppsf in cur.fetchall():
                results[hood][str(year)] = {
                    "count": count,
                    "median_price": price,
                    "median_ppsf": round(ppsf, 2) if ppsf else None
                }
        
        # Fill missing years for consistency
        current_year = datetime.now().year
        all_years = [str(y) for y in range(start_year, current_year + 2)]
        
        for hood in results:
            for y in all_years:
                if y not in results[hood]:
                    results[hood][y] = {"count": 0, "median_price": None, "median_ppsf": None}

        return results

    def get_flood_stats(self, hoods):
        sql = """
        SELECT 
            a.neighborhood_code,
            f.fld_zone,
            COUNT(*) 
        FROM assessor a
        JOIN flood_skagit_fema f 
          ON a.centroid_geog && f.geom 
          AND ST_Intersects(a.centroid_geog, f.geom)
        WHERE a.neighborhood_code = ANY(%s)
        GROUP BY a.neighborhood_code, f.fld_zone
        """
        data = defaultdict(dict)
        totals = defaultdict(int)
        with connection.cursor() as cur:
            cur.execute(sql, (hoods,))
            for hood, zone, cnt in cur.fetchall():
                data[hood][zone] = cnt
                totals[hood] += cnt
        results = {}
        for hood, zones in data.items():
            t = totals[hood]
            results[hood] = {z: round((c/t)*100, 2) for z, c in zones.items()}
        return results

    def get_slope_stats(self, hoods):
        sql = """
        SELECT 
            a.neighborhood_code,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY ST_Value(t.rast, a.centroid_geog::geometry)) as med,
            PERCENTILE_CONT(0.75) WITHIN GROUP(ORDER BY ST_Value(t.rast, a.centroid_geog::geometry)) as p75,
            COUNT(*)
        FROM dem_slope_tiles t
        JOIN assessor a ON ST_Intersects(t.rast, a.centroid_geog::geometry)
        WHERE a.neighborhood_code = ANY(%s)
        GROUP BY a.neighborhood_code
        """
        results = {}
        with connection.cursor() as cur:
            cur.execute(sql, (hoods,))
            for hood, med, p75, cnt in cur.fetchall():
                results[hood] = {"median": med, "p75": p75, "count": cnt}
        return results

    def get_census_stats(self, hoods):
        sql = """
        SELECT 
            a.neighborhood_code,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acs.median_income) as inc,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acs.population) as pop,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acs.edu_bachelor) as bach,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acs.edu_master) as mast,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acs.edu_professional) as prof,
            PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY acs.edu_doctorate) as doc,
            COUNT(*)
        FROM assessor a
        JOIN census.bg_skagit bg 
          ON ST_Intersects(bg.geom, ST_Transform(a.centroid_geog::geometry, 2285))
        JOIN census.acs_bg_skagit acs ON bg.geoid = acs.geoid
        WHERE a.neighborhood_code = ANY(%s)
        GROUP BY a.neighborhood_code
        """
        results = {}
        with connection.cursor() as cur:
            cur.execute(sql, (hoods,))
            for row in cur.fetchall():
                results[row[0]] = {
                    "median_income": row[1],
                    "median_population": row[2],
                    "education": {
                        "bachelor": row[3], "master": row[4], "professional": row[5], "doctorate": row[6]
                    },
                    "samples": row[7]
                }
        return results

    def get_amenity_stats_optimized(self, hoods):
        tables = {
            "dist_school_m": "osm.osm_schools",
            "dist_park_m": "osm.osm_parks",
            "dist_major_road_m": "osm.osm_major_roads"
        }
        final_results = defaultdict(dict)
        for json_key, table_name in tables.items():
            sql = f"""
            SELECT 
                a.neighborhood_code,
                PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY nearest.dist)
            FROM assessor a
            CROSS JOIN LATERAL (
                SELECT ST_Distance(a.centroid_geog, ST_Transform(t.geom, 4326)::geography) as dist
                FROM {table_name} t
                ORDER BY a.centroid_geog <-> ST_Transform(t.geom, 4326)::geography
                LIMIT 1
            ) nearest
            WHERE a.neighborhood_code = ANY(%s)
            GROUP BY a.neighborhood_code
            """
            with connection.cursor() as cur:
                cur.execute(sql, (hoods,))
                for hood, dist in cur.fetchall():
                    final_results[hood][json_key] = dist
        return final_results