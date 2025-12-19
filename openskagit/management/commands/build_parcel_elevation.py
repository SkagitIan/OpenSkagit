from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Compute parcel elevation metrics (elev, slope, aspect, aspect_dir) from reference_elevation raster."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roll",
            type=int,
            help="Optional roll_id filter on master_parcel",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10000,
            help="Number of parcels to process per batch (default: 10000)",
        )

    def handle(self, *args, **options):
        roll_id = options.get("roll")
        batch_size = options.get("batch_size", 10000)

        self.stdout.write(
            self.style.MIGRATE_HEADING("Computing parcel elevation metrics from reference_elevation")
        )

        with connection.cursor() as cursor:
            # Run the optimized elevation update with progress reporting
            updated_count = run_elevation_metrics(cursor, roll_id, batch_size, self.stdout)

            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Successfully updated {updated_count:,} parcels with elevation metrics"
                )
            )

def run_elevation_metrics(cursor, roll_id=None, batch_size=5000, stdout=None):
    """
    Fast, resumable raster → parcel elevation pipeline (string PK safe).
    """

    params = []
    roll_filter = ""
    if roll_id is not None:
        roll_filter = "AND mp.roll = %s"
        params.append(roll_id)

    last_parcel_id = None
    total_updated = 0
    batch_num = 0

    if stdout:
        stdout.write(f"Processing parcels in batches of {batch_size:,}…")

    while True:
        # Pull the next batch of parcel IDs deterministically
        cursor.execute(
            f"""
            SELECT pg.parcel_id
            FROM openskagit_parcelgeometry pg
            JOIN master_parcel mp ON mp.parcel_number = pg.parcel_id
            WHERE pg.centroid_2926 IS NOT NULL
              {roll_filter}
              { "AND pg.parcel_id > %s" if last_parcel_id else "" }
            ORDER BY pg.parcel_id
            LIMIT %s
            """,
            ([last_parcel_id] if last_parcel_id else []) + params + [batch_size],
        )

        rows = cursor.fetchall()
        if not rows:
            break

        parcel_ids = [r[0] for r in rows]
        last_parcel_id = parcel_ids[-1]
        batch_num += 1

        parcel_ids_sql = ",".join(f"'{pid}'" for pid in parcel_ids)

        batch_sql = f"""
        WITH parcel_batch AS (
            SELECT
                pg.parcel_id,
                ST_Transform(pg.centroid_2926, ST_SRID(r.rast)) AS pt,
                r.rast
            FROM openskagit_parcelgeometry pg
            JOIN reference_elevation r
              ON r.rast && ST_Expand(
                   ST_Transform(pg.centroid_2926, ST_SRID(r.rast)),
                   1
                 )
             AND ST_Intersects(
                   r.rast,
                   ST_Transform(pg.centroid_2926, ST_SRID(r.rast))
                 )
            WHERE pg.parcel_id IN ({parcel_ids_sql})
              AND pg.centroid_2926 IS NOT NULL
        ),
        computed AS (
            SELECT
                parcel_id,
                ST_Value(rast, 1, pt) AS elev_val,
                ST_Value(ST_Slope(rast, 1, '32BF', 'DEGREES'), 1, pt) AS slope_val,
                ST_Value(ST_Aspect(rast, 1, '32BF'), 1, pt) AS aspect_val
            FROM parcel_batch
        )
        UPDATE openskagit_parcelgeometry pg
        SET
            elev = c.elev_val,
            slope = c.slope_val,
            aspect = c.aspect_val,
            aspect_dir = CASE
                WHEN c.aspect_val IS NULL THEN NULL
                WHEN c.aspect_val >= 337.5 OR c.aspect_val < 22.5 THEN 'N'
                WHEN c.aspect_val < 67.5 THEN 'NE'
                WHEN c.aspect_val < 112.5 THEN 'E'
                WHEN c.aspect_val < 157.5 THEN 'SE'
                WHEN c.aspect_val < 202.5 THEN 'S'
                WHEN c.aspect_val < 247.5 THEN 'SW'
                WHEN c.aspect_val < 292.5 THEN 'W'
                WHEN c.aspect_val < 337.5 THEN 'NW'
                ELSE NULL
            END
        FROM computed c
        WHERE pg.parcel_id = c.parcel_id;
        """

        cursor.execute(batch_sql)
        batch_updated = cursor.rowcount
        total_updated += batch_updated

        if stdout:
            stdout.write(
                f"  Batch {batch_num}: updated {batch_updated:,} "
                f"(total {total_updated:,}, last={last_parcel_id})"
            )

    return total_updated
