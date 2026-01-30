from django.core.management.base import BaseCommand
from django.db import connection, transaction

class Command(BaseCommand):
    help = "Load parcel geometry from reference_parcels into openskagit_parcelgeometry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help="Only process a limited number of reference parcels",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Loading parcel geometry…"))

        limit = options.get("limit")

        with transaction.atomic(), connection.cursor() as cur:

            cur.execute("SET work_mem = '540MB';")
            cur.execute("SET max_parallel_workers_per_gather = 4;")

            # 1. Insert/update geometry directly from reference_parcels
            self.stdout.write("Upserting parcel geometries from reference_parcels…")
            cur.execute("""
                WITH source AS (
                    SELECT
                        "PARCELID"::text AS parcel_id,
                        ST_Multi("geometry")::geometry(MULTIPOLYGON, 2926) AS geom_2926
                    FROM reference_parcels
                    WHERE "PARCELID" IS NOT NULL
                      AND "geometry" IS NOT NULL
                      AND NOT ST_IsEmpty("geometry")
                    ORDER BY "PARCELID"
                    LIMIT COALESCE(%(limit)s, 1000000000)
                ),
                updated AS (
                    UPDATE openskagit_parcelgeometry pg
                    SET geom_2926 = source.geom_2926
                    FROM source
                    WHERE pg.parcel_id = source.parcel_id
                      AND pg.geom_2926 IS DISTINCT FROM source.geom_2926
                    RETURNING pg.parcel_id
                ),
                inserted AS (
                    INSERT INTO openskagit_parcelgeometry (parcel_id, geom_2926)
                    SELECT source.parcel_id, source.geom_2926
                    FROM source
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM openskagit_parcelgeometry pg
                        WHERE pg.parcel_id = source.parcel_id
                    )
                    RETURNING parcel_id
                ),
                touched AS (
                    SELECT parcel_id FROM updated
                    UNION ALL
                    SELECT parcel_id FROM inserted
                ),
                centroided AS (
                    UPDATE openskagit_parcelgeometry
                    SET
                        centroid_geog = (
                            ST_Transform(
                                ST_Centroid(geom_2926)::geometry,
                                4326
                            )
                        )::geometry(Point,4326),
                        latitude = ST_Y(ST_Transform(ST_Centroid(geom_2926), 4326)),
                        longitude = ST_X(ST_Transform(ST_Centroid(geom_2926), 4326))
                    WHERE parcel_id IN (SELECT parcel_id FROM touched)
                    RETURNING 1
                )
                SELECT
                    (SELECT COUNT(*) FROM inserted) AS inserted_count,
                    (SELECT COUNT(*) FROM updated) AS updated_count,
                    (SELECT COUNT(*) FROM centroided) AS centroid_count;
            """, {"limit": limit})
            inserted, updated, centroid_updated = cur.fetchone()
            self.stdout.write(self.style.SUCCESS(f"Inserted {inserted} geometries."))
            self.stdout.write(self.style.SUCCESS(f"Updated {updated} geometries."))
            self.stdout.write(self.style.SUCCESS(f"Updated {centroid_updated} centroids."))

            # 2. Delete parcels no longer in reference_parcels
            if limit:
                deleted = 0
            else:
                cur.execute("""
                    DELETE FROM openskagit_parcelgeometry pg
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM reference_parcels rp
                        WHERE rp."PARCELID"::text = pg.parcel_id
                    );
                """)
                deleted = cur.rowcount
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} stale parcels."))

            # 3. Optional: index geometry for fast spatial operations
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
        
        if limit:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT "PARCELID"::text
                    FROM reference_parcels
                    WHERE "PARCELID" IS NOT NULL
                    ORDER BY "PARCELID"
                    LIMIT %s;
                    """,
                    [limit],
                )
                target_ids = [row[0] for row in cur.fetchall()]
            self.stdout.write(f"target_ids={target_ids}")
        self.stdout.write(self.style.SUCCESS("Parcel geometry load complete."))
