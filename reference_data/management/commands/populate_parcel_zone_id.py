from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Populate parcel_planning_facts.zone_id using spatial overlap with reference_zoning_zones"

    def handle(self, *args, **options):
        self.stdout.write("Starting parcel zoning assignment…")

        sql = """
        BEGIN;

        -- 1. Ensure column exists
        ALTER TABLE public.parcel_planning_facts
        ADD COLUMN IF NOT EXISTS zone_id TEXT;

        -- 2. Reset existing values
        UPDATE public.parcel_planning_facts
        SET zone_id = NULL;

        -- 3. Assign primary zone by largest overlap
        WITH ranked_zones AS (
            SELECT
                ppf.parcel_id,
                rz.zoneid,
                ROW_NUMBER() OVER (
                    PARTITION BY ppf.parcel_id
                    ORDER BY ST_Area(
                        ST_Intersection(
                            ST_MakeValid(pg.geom_2926),
                            ST_MakeValid(rz.geom)
                        )
                    ) DESC
                ) AS rn
            FROM public.parcel_planning_facts ppf
            JOIN public.openskagit_parcelgeometry pg
                ON pg.parcel_id = ppf.parcel_id
            JOIN public.reference_zoning_zones rz
                ON ST_Intersects(
                    ST_MakeValid(pg.geom_2926),
                    ST_MakeValid(rz.geom)
                )
            WHERE pg.geom_2926 IS NOT NULL
              AND rz.geom IS NOT NULL
        )
        UPDATE public.parcel_planning_facts ppf
        SET zone_id = rz.zoneid
        FROM ranked_zones rz
        WHERE ppf.parcel_id = rz.parcel_id
          AND rz.rn = 1;

        COMMIT;
        """

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)

        # Verification
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    COUNT(*) AS total_parcels,
                    COUNT(zone_id) AS parcels_with_zone,
                    ROUND(100.0 * COUNT(zone_id) / COUNT(*), 2) AS pct_zoned
                FROM public.parcel_planning_facts;
            """)
            total, zoned, pct = cursor.fetchone()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Zoned {zoned:,} of {total:,} parcels ({pct}%)."
            )
        )
