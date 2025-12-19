from django.core.management.base import BaseCommand
from django.db import connection, transaction

class Command(BaseCommand):
    help = "Load parcel geometry from reference_parcels into openskagit_parcelgeometry."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Loading parcel geometry…"))

        with transaction.atomic(), connection.cursor() as cur:

            # 1. Clear existing geometry table
            self.stdout.write("Truncating openskagit_parcelgeometry…")
            cur.execute("TRUNCATE TABLE openskagit_parcelgeometry RESTART IDENTITY;")

            # 2. Insert new geometry directly from reference_parcels
            self.stdout.write("Inserting parcel geometries from reference_parcels…")
            cur.execute("""
                INSERT INTO openskagit_parcelgeometry (parcel_id, geom_2926)
                SELECT 
                    "PARCELID"::text AS parcel_id,
                    ST_Multi("geometry")::geometry(MULTIPOLYGON, 2926) AS geom_2926
                FROM reference_parcels
                WHERE "PARCELID" IS NOT NULL
                AND "geometry" IS NOT NULL
                AND NOT ST_IsEmpty("geometry");


            """)
            inserted = cur.rowcount
            self.stdout.write(self.style.SUCCESS(f"Inserted {inserted} geometries."))

            # 3. Update centroids, lat/lon
            self.stdout.write("Computing centroids and lat/lon…")
            cur.execute("""
                UPDATE openskagit_parcelgeometry
                SET 
                    centroid_geog = (
                        ST_Transform(
                            ST_Centroid(geom_2926)::geometry,
                            4326
                        )
                    )::geometry(Point,4326),
                    latitude = ST_Y(ST_Transform(ST_Centroid(geom_2926), 4326)),
                    longitude = ST_X(ST_Transform(ST_Centroid(geom_2926), 4326));

            """)
            updated = cur.rowcount
            self.stdout.write(self.style.SUCCESS(f"Updated {updated} centroids."))

            # 4. Optional: index geometry for fast spatial operations
            self.stdout.write("Ensuring spatial index exists…")
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes 
                        WHERE tablename='openskagit_parcelgeometry'
                          AND indexname='openskagit_parcelgeometry_geom_2926_gix'
                    ) THEN
                        CREATE INDEX openskagit_parcelgeometry_geom_2926_gix
                        ON openskagit_parcelgeometry
                        USING GIST (geom_2926);
                    END IF;
                END$$;
            """)
        
        self.stdout.write(self.style.SUCCESS("Parcel geometry load complete."))
