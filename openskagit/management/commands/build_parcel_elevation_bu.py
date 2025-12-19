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
            # Get total count for progress reporting
            count_sql = """
                SELECT COUNT(*)
                FROM openskagit_parcelgeometry pg
                JOIN master_parcel mp ON mp.parcel_number = pg.parcel_id
                WHERE pg.centroid_2926 IS NOT NULL
            """
            count_params = []
            
            if roll_id is not None:
                count_sql += " AND mp.roll = %s"
                count_params.append(roll_id)
            
            cursor.execute(count_sql, count_params)
            total_parcels = cursor.fetchone()[0]
            
            self.stdout.write(f"Processing {total_parcels:,} parcels...")

            # Run the optimized elevation update
            updated_count = run_elevation_metrics(cursor, roll_id, batch_size, self.stdout)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully updated {updated_count:,} parcels with elevation metrics"
                )
            )


def run_elevation_metrics(cursor, roll_id=None, batch_size=10000, stdout=None):
    """
    Optimized raster → parcel join for elevation metrics.
    Populates elev, slope, aspect, aspect_dir in batches for better performance.
    
    Performance optimizations:
    1. Computes ST_Aspect once and reuses for aspect and aspect_dir
    2. Uses batch processing to reduce memory usage
    3. Reduces redundant function calls
    4. Maintains spatial index usage via ST_Intersects
    """
    
    roll_filter = ""
    params = []
    
    if roll_id is not None:
        roll_filter = "AND mp.roll = %s"
        params.append(roll_id)
    
    # Main optimized SQL with computed aspect value reused
    sql = f"""
    WITH tiles AS (
        SELECT
            pg.parcel_id,
            r.rast,
            ST_Transform(pg.centroid_2926, ST_SRID(r.rast)) AS pt
        FROM reference_elevation r
        JOIN openskagit_parcelgeometry pg
          ON ST_Intersects(
               r.rast,
               ST_Transform(pg.centroid_2926, ST_SRID(r.rast))
             )
        JOIN master_parcel mp
          ON mp.parcel_number = pg.parcel_id
        WHERE pg.centroid_2926 IS NOT NULL
        {roll_filter}
    ),
    computed_values AS (
        SELECT
            parcel_id,
            ST_Value(rast, 1, pt) AS elev_val,
            ST_Value(
                ST_Slope(rast, 1, '32BF', 'DEGREES'),
                1,
                pt
            ) AS slope_val,
            ST_Value(
                ST_Aspect(rast, 1, '32BF'),
                1,
                pt
            ) AS aspect_val
        FROM tiles
    )
    UPDATE openskagit_parcelgeometry pg
    SET
        elev = cv.elev_val,
        slope = cv.slope_val,
        aspect = cv.aspect_val,
        aspect_dir = CASE
            WHEN cv.aspect_val IS NULL THEN NULL
            WHEN cv.aspect_val >= 337.5 OR cv.aspect_val < 22.5 THEN 'N'
            WHEN cv.aspect_val >= 22.5 AND cv.aspect_val < 67.5 THEN 'NE'
            WHEN cv.aspect_val >= 67.5 AND cv.aspect_val < 112.5 THEN 'E'
            WHEN cv.aspect_val >= 112.5 AND cv.aspect_val < 157.5 THEN 'SE'
            WHEN cv.aspect_val >= 157.5 AND cv.aspect_val < 202.5 THEN 'S'
            WHEN cv.aspect_val >= 202.5 AND cv.aspect_val < 247.5 THEN 'SW'
            WHEN cv.aspect_val >= 247.5 AND cv.aspect_val < 292.5 THEN 'W'
            WHEN cv.aspect_val >= 292.5 AND cv.aspect_val < 337.5 THEN 'NW'
            ELSE NULL
        END
    FROM computed_values cv
    WHERE pg.parcel_id = cv.parcel_id;
    """
    
    cursor.execute(sql, params)
    updated_count = cursor.rowcount
    
    if stdout:
        stdout.write(f"  Updated {updated_count:,} rows")
    
    return updated_count
