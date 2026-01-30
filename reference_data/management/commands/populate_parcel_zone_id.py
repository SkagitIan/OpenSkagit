from django.core.management.base import BaseCommand
from django.db import connection, transaction

from reference_data.management.commands.spatial_eval import dataset_is_available


class Command(BaseCommand):
    help = "Populate parcel_planning_facts.zone_id using point-in-polygon zoning"

    def handle(self, *args, **options):
        self.stdout.write("Assigning parcel zoning (point-on-surface)…")

        dataset_available = dataset_is_available("reference_zoning_zones")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    ALTER TABLE public.parcel_planning_facts
                    ADD COLUMN IF NOT EXISTS zone_id TEXT;
                """)
                cursor.execute("""
                    UPDATE public.parcel_planning_facts
                    SET zone_id = NULL;
                """)
                if not dataset_available:
                    self.stdout.write(
                        self.style.WARNING(
                            "reference_zoning_zones unavailable; zone_id set to unknown."
                        )
                    )
                else:
                    cursor.execute("""
                        UPDATE public.parcel_planning_facts ppf
                        SET zone_id = rz.zoneid
                        FROM public.openskagit_parcelgeometry pg
                        JOIN public.reference_zoning_zones rz
                          ON ST_Contains(
                                rz.geom_valid,
                                ST_PointOnSurface(pg.geom_2926_valid)
                             )
                        WHERE ppf.parcel_id = pg.parcel_id
                          AND pg.geom_2926_valid IS NOT NULL
                          AND rz.geom_valid IS NOT NULL;
                    """)

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
