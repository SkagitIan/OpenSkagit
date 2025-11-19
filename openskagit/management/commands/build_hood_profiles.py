import statistics
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import connection

from openskagit.models import (
    Assessor,
    Improvements,
    Land,
    Sales,
    NeighborhoodProfile,
    NeighborhoodGeom,
)
from django.db.models import Q
from decimal import Decimal

def convert_decimals(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj


class Command(BaseCommand):
    help = "Build complete neighborhood snapshot JSON for all neighborhoods."
    def add_arguments(self, parser):
            parser.add_argument(
                "--hood",
                type=str,
                help="Optional: build profile for a single neighborhood code.",
            )
    def handle(self, *args, **options):
        only_hood = options.get("hood")
        allowed = (
            Q(neighborhood_code__startswith="20B")  |
            Q(neighborhood_code__startswith="21B")  |
            Q(neighborhood_code__startswith="22B")  |
            Q(neighborhood_code__startswith="23B")  |
            Q(neighborhood_code__startswith="26B")  |
            Q(neighborhood_code__startswith="27B")  |

            Q(neighborhood_code__startswith="20LC") |
            Q(neighborhood_code__startswith="21LC") |
            Q(neighborhood_code__startswith="22LC") |
            Q(neighborhood_code__startswith="23LC") |
            Q(neighborhood_code__startswith="20CON") |
            Q(neighborhood_code__startswith="22CON") |

            Q(neighborhood_code__startswith="20A")  |
            Q(neighborhood_code__startswith="21A")  |
            Q(neighborhood_code__startswith="22A")  |
            Q(neighborhood_code__startswith="23A")  |
            Q(neighborhood_code__startswith="20FID") |
            Q(neighborhood_code__startswith="22FID") |
            Q(neighborhood_code__startswith="20GUEM") |
            Q(neighborhood_code__startswith="22GUEM") |

            Q(neighborhood_code__startswith="20SW") |
            Q(neighborhood_code__startswith="21SW") |
            Q(neighborhood_code__startswith="22SW") |
            Q(neighborhood_code__startswith="23SW") |

            Q(neighborhood_code__startswith="20CC") |
            Q(neighborhood_code__startswith="22CC") |
            Q(neighborhood_code__startswith="10CC") |

            Q(neighborhood_code__startswith="20MV") |
            Q(neighborhood_code__startswith="21MV") |
            Q(neighborhood_code__startswith="22MV") |
            Q(neighborhood_code__startswith="23MV")
        )

        if only_hood:
            hoods = [only_hood]
        else:
            hoods = (
                Assessor.objects
                .filter(allowed)
                .exclude(neighborhood_code__isnull=True)
                .values_list("neighborhood_code", flat=True)
                .distinct()
            )




        self.stdout.write(f"Found {len(hoods)} neighborhoods.")

        for hood in hoods:
            self.stdout.write(f"Processing hood {hood}…")

            parcels = Assessor.objects.filter(neighborhood_code=hood)

            if not parcels.exists():
                continue

            json_blob = {}

            # ----------------------------------------------------------
            # BASIC PARCEL COUNT
            # ----------------------------------------------------------
            json_blob["parcel_count"] = parcels.count()

            # ----------------------------------------------------------
            # NEIGHBORHOOD NAME (from Assessor, as requested)
            # ----------------------------------------------------------
            first_parcel = parcels.first()
            nbhd_desc = (
                getattr(first_parcel, "neighborhood_code_description", None)
                if first_parcel
                else None
            )
            json_blob["neighborhood_name"] = nbhd_desc or hood

            # Optional: keep geom name separately if you want it later
            ngeo = NeighborhoodGeom.objects.filter(code=hood).first()
            if ngeo:
                json_blob["geom_name"] = ngeo.name

            # ----------------------------------------------------------
            # YEAR BUILT + AGE BANDS + OLDEST / NEWEST + NEW BUILDS
            # ----------------------------------------------------------
            years = list(
                parcels.exclude(year_built__isnull=True)
                .values_list("year_built", flat=True)
            )

            json_blob["median_year_built"] = statistics.median(years) if years else None

            # Oldest / newest
            json_blob["oldest_year_built"] = min(years) if years else None
            json_blob["newest_year_built"] = max(years) if years else None

            # Age bands
            agebands = {"0_20": 0, "20_40": 0, "40_60": 0, "60_plus": 0}
            now = datetime.now().year

            for y in years:
                age = now - y
                if age <= 20:
                    agebands["0_20"] += 1
                elif age <= 40:
                    agebands["20_40"] += 1
                elif age <= 60:
                    agebands["40_60"] += 1
                else:
                    agebands["60_plus"] += 1

            json_blob["age_distribution"] = agebands

            # New building activity (hard-coded recent years)
            new_build_counts = {
                str(year): parcels.filter(year_built=year).count()
                for year in (2023, 2024, 2025)
            }
            json_blob["new_builds"] = new_build_counts

            # ----------------------------------------------------------
            # LIVING AREA
            # ----------------------------------------------------------
            glas = list(
                parcels.exclude(living_area__isnull=True)
                .values_list("living_area", flat=True)
            )

            if glas:
                s = sorted(glas)
                json_blob["living_area_stats"] = {
                    "median": statistics.median(s),
                    "p25": s[len(s) // 4],
                    "p75": s[(len(s) * 3) // 4],
                    "sample_size": len(s),
                }
            else:
                json_blob["living_area_stats"] = None

            # ----------------------------------------------------------
            # LOT SIZE (ACRES)
            # ----------------------------------------------------------
            acres = list(
                parcels.exclude(acres__isnull=True)
                .values_list("acres", flat=True)
            )

            if acres:
                s = sorted(acres)
                json_blob["lot_size"] = {
                    "median_acres": statistics.median(s),
                    "p25": s[len(s) // 4],
                    "p75": s[(len(s) * 3) // 4],
                    "sample_size": len(s),
                }
            else:
                json_blob["lot_size"] = None

            # ----------------------------------------------------------
            # BATHROOMS (Assessor only, more descriptive)
            # ----------------------------------------------------------
            baths = list(
                parcels.exclude(bathrooms__isnull=True)
                .values_list("bathrooms", flat=True)
            )

            if baths:
                baths_sorted = sorted(baths)
                median_baths = statistics.median(baths_sorted)
                # More descriptive distribution
                distribution = []
                for val in sorted(set(baths_sorted)):
                    count = baths_sorted.count(val)
                    # label like "1 bath", "1.75 baths"
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

            # ----------------------------------------------------------
            # BASEMENT %
            # ----------------------------------------------------------
            finished = parcels.filter(finished_basement__gt=0).count()
            unfinished = parcels.filter(unfinished_basement__gt=0).count()
            total = parcels.count()

            if total > 0:
                pct = round(((finished + unfinished) / total) * 100, 2)
            else:
                pct = None

            json_blob["basement_pct"] = pct

            # ----------------------------------------------------------
            # GARAGE
            # ----------------------------------------------------------
            garages = list(
                parcels.exclude(garage_sqft__isnull=True)
                .values_list("garage_sqft", flat=True)
            )

            json_blob["garage"] = {
                "median_sqft": statistics.median(garages) if garages else None,
                "sample_size": len(garages),
            }

            # ----------------------------------------------------------
            # BUILDING STYLE (more descriptive structure)
            # ----------------------------------------------------------
            style_values = list(
                parcels.exclude(building_style__isnull=True)
                .values_list("building_style", flat=True)
            )

            if style_values:
                total_styles = len(style_values)
                counts = {}
                for st in style_values:
                    counts[st] = counts.get(st, 0) + 1

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

            # NOTE: land_use_mix DROPPED per your request

            # ----------------------------------------------------------
            # FLOOD (FEMA)
            # ----------------------------------------------------------
            json_blob["flood_profile"] = self.get_flood_stats(parcels)

            # ----------------------------------------------------------
            # SLOPE
            # ----------------------------------------------------------
            json_blob["slope_stats"] = self.get_slope_stats(parcels)

            # ----------------------------------------------------------
            # CENSUS (fixed for SRID 2285)
            # ----------------------------------------------------------
            json_blob["census"] = self.get_census_stats(parcels)

            # ----------------------------------------------------------
            # AMENITIES (OSM)
            # ----------------------------------------------------------
            json_blob["amenities"] = self.get_amenity_stats(parcels)

            # ----------------------------------------------------------
            # SALES (ignore zero prices)
            # ----------------------------------------------------------
            json_blob["sales"] = self.get_sale_stats(parcels)

            # Skip neighborhoods with insufficient sales
            sale_info = json_blob.get("sales", {})
            sale_count = sale_info.get("sale_count", 0)

            if sale_count < 15:
                self.stdout.write(
                    self.style.WARNING(f"Skipping {hood}: only {sale_count} sales (< 15 required)")
                )
                continue

            # ----------------------------------------------------------
            # SAVE
            # ----------------------------------------------------------
            NeighborhoodProfile.objects.update_or_create(
                hood_id=hood,
                defaults={"json_data": convert_decimals(json_blob)},
            )


            self.stdout.write(f"✓ Hood {hood} saved.")

        self.stdout.write("Done building neighborhood snapshots.")

    # ==============================================================  
    # SUB-FUNCTIONS  
    # ==============================================================

    def get_flood_stats(self, parcels):
        sql = """
        SELECT fld_zone, COUNT(*)
        FROM flood_skagit_fema f, assessor a
        WHERE a.id = ANY(%s)
          AND a.geom IS NOT NULL
          AND ST_Intersects(ST_Centroid(a.geom), f.geom)
        GROUP BY fld_zone;
        """

        ids = list(parcels.values_list("id", flat=True))

        with connection.cursor() as cur:
            cur.execute(sql, (ids,))
            rows = cur.fetchall()

        total = sum(r[1] for r in rows) or 1
        return {r[0]: round((r[1] / total) * 100, 2) for r in rows}

    def get_slope_stats(self, parcels):
        sql = """
        SELECT ST_Value(t.rast, ST_Centroid(a.geom)) AS slope
        FROM dem_slope_tiles t, assessor a
        WHERE a.id = ANY(%s)
          AND a.geom IS NOT NULL
          AND ST_Intersects(t.rast, a.geom)
        """

        ids = list(parcels.values_list("id", flat=True))

        with connection.cursor() as cur:
            cur.execute(sql, (ids,))
            slopes = [r[0] for r in cur.fetchall() if r[0] is not None]

        if not slopes:
            return {}

        slopes_sorted = sorted(slopes)

        return {
            "median": statistics.median(slopes_sorted),
            "p75": slopes_sorted[int(len(slopes_sorted) * 0.75)],
            "count": len(slopes_sorted),
        }

    def get_census_stats(self, parcels):
        """
        Join assessor → bg_skagit (geom, SRID 2285) → acs_bg_skagit (attributes).
        """
        sql = """
        SELECT 
            acs.median_income,
            acs.population,
            acs.edu_bachelor,
            acs.edu_master,
            acs.edu_professional,
            acs.edu_doctorate
        FROM assessor a
        JOIN census.bg_skagit bg
          ON ST_Intersects(
                bg.geom,
                ST_Transform(ST_Centroid(a.geom), 2285)
             )
        JOIN census.acs_bg_skagit acs
          ON bg.geoid = acs.geoid
        WHERE a.id = ANY(%s)
          AND a.geom IS NOT NULL;
        """

        ids = list(parcels.values_list("id", flat=True))

        with connection.cursor() as cur:
            cur.execute(sql, (ids,))
            rows = cur.fetchall()

        if not rows:
            return {}

        incomes = [r[0] for r in rows if r[0] is not None]
        pops = [r[1] for r in rows if r[1] is not None]
        bachelor = [r[2] for r in rows if r[2] is not None]
        master = [r[3] for r in rows if r[3] is not None]
        professional = [r[4] for r in rows if r[4] is not None]
        doctorate = [r[5] for r in rows if r[5] is not None]

        return {
            "median_income": statistics.median(incomes) if incomes else None,
            "median_population": statistics.median(pops) if pops else None,
            "education": {
                "bachelor": statistics.median(bachelor) if bachelor else None,
                "master": statistics.median(master) if master else None,
                "professional": statistics.median(professional) if professional else None,
                "doctorate": statistics.median(doctorate) if doctorate else None,
            },
            "samples": len(rows),
        }

    def get_amenity_stats(self, parcels):
        def nearest_distances(sql, ids):
            with connection.cursor() as cur:
                cur.execute(sql, (ids,))
                rows = [r[0] for r in cur.fetchall() if r[0] is not None]
            return rows

        ids = list(parcels.values_list("id", flat=True))

        # Schools
        sql_schools = """
            SELECT
                MIN(
                    ST_Distance(
                        ST_Transform(a.geom, 4326)::geography,
                        ST_Transform(s.geom, 4326)::geography
                    )
                ) AS dist_m
            FROM assessor a
            JOIN LATERAL (
                SELECT geom
                FROM osm.osm_schools
            ) s ON TRUE
            WHERE a.id = ANY(%s)
            GROUP BY a.id;
        """

        school_dists = nearest_distances(sql_schools, ids)

        # Parks
        sql_parks = """
            SELECT
                MIN(
                    ST_Distance(
                        ST_Transform(a.geom, 4326)::geography,
                        ST_Transform(p.geom, 4326)::geography
                    )
                ) AS dist_m
            FROM assessor a
            JOIN LATERAL (
                SELECT geom
                FROM osm.osm_parks
            ) p ON TRUE
            WHERE a.id = ANY(%s)
            GROUP BY a.id;
        """

        park_dists = nearest_distances(sql_parks, ids)

        # Major Roads
        sql_roads = """
            SELECT
                MIN(
                    ST_Distance(
                        ST_Transform(a.geom, 4326)::geography,
                        ST_Transform(r.geom, 4326)::geography
                    )
                ) AS dist_m
            FROM assessor a
            JOIN LATERAL (
                SELECT geom
                FROM osm.osm_major_roads
            ) r ON TRUE
            WHERE a.id = ANY(%s)
            GROUP BY a.id;
        """

        road_dists = nearest_distances(sql_roads, ids)

        def median_or_none(arr):
            return statistics.median(arr) if arr else None

        return {
            "dist_school_m": median_or_none(school_dists),
            "dist_park_m": median_or_none(park_dists),
            "dist_major_road_m": median_or_none(road_dists),
        }

    def get_sale_stats(self, parcels):
        two_years_ago = datetime.now() - timedelta(days=730)

        sales = (
            Sales.objects.filter(
                parcel_number__in=parcels.values_list("parcel_number", flat=True),
                sale_date__gte=two_years_ago,
            )
            .filter(sale_price__gt=0)
        )

        if not sales.exists():
            return {}

        prices = list(sales.values_list("sale_price", flat=True))

        return {
            "sale_count": sales.count(),
            "median_sale_price": statistics.median(prices),
        }
