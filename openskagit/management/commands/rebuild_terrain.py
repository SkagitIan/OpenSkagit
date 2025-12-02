from django.core.management.base import BaseCommand
from django.db import connection
from openskagit.models import Assessor


class Command(BaseCommand):
    help = "Rebuild slope + aspect from DEM, sample values into assessor, and compute aspect_dir."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting DEM terrain rebuild…"))

        sql = """

        ----------------------------------------------------------------------
        -- 0. Clean any old working tables
        ----------------------------------------------------------------------
        DROP TABLE IF EXISTS dem_skagit_2926;
        DROP TABLE IF EXISTS dem_slope_2926;
        DROP TABLE IF EXISTS dem_aspect_2926;

        ----------------------------------------------------------------------
        -- 1. Reproject DEM to EPSG:2926 (meters)
        ----------------------------------------------------------------------
        CREATE TABLE dem_skagit_2926 AS
        SELECT ST_Transform(rast, 2926) AS rast
        FROM dem_skagit;

        CREATE INDEX dem_skagit_2926_rast_gix
        ON dem_skagit_2926 USING gist (ST_ConvexHull(rast));

        ANALYZE dem_skagit_2926;

        ----------------------------------------------------------------------
        -- 2. Build slope raster in degrees
        ----------------------------------------------------------------------
        CREATE TABLE dem_slope_2926 AS
        SELECT
            ST_Slope(
                rast,
                1,              -- input band
                '32BF',         -- float
                'DEGREES',      -- slope in degrees
                1,
                FALSE
            ) AS rast
        FROM dem_skagit_2926;

        CREATE INDEX dem_slope_2926_rast_gix
        ON dem_slope_2926 USING gist (ST_ConvexHull(rast));

        ANALYZE dem_slope_2926;

        ----------------------------------------------------------------------
        -- 3. Build aspect raster in degrees
        ----------------------------------------------------------------------
        CREATE TABLE dem_aspect_2926 AS
        SELECT
            ST_Aspect(
                rast,
                1,
                '32BF',
                'DEGREES',
                1
            ) AS rast
        FROM dem_skagit_2926;

        CREATE INDEX dem_aspect_2926_rast_gix
        ON dem_aspect_2926 USING gist (ST_ConvexHull(rast));

        ANALYZE dem_aspect_2926;

        ----------------------------------------------------------------------
        -- 4. Sample slope into assessor.slope
        -- Using centroid of geom_2926 + raster tile intersects
        ----------------------------------------------------------------------
        WITH slope_samples AS (
            SELECT 
                a.parcel_number,
                ST_Value(s.rast, 1, ST_Centroid(a.geom_2926)) AS val
            FROM assessor a
            JOIN dem_slope_2926 s
              ON ST_Intersects(s.rast, a.geom_2926)
        )
        UPDATE assessor a
        SET slope = s.val
        FROM slope_samples s
        WHERE a.parcel_number = s.parcel_number;

        ----------------------------------------------------------------------
        -- 5. Sample aspect into assessor.aspect
        ----------------------------------------------------------------------
        WITH aspect_samples AS (
            SELECT 
                a.parcel_number,
                ST_Value(t.rast, 1, ST_Centroid(a.geom_2926)) AS val
            FROM assessor a
            JOIN dem_aspect_2926 t
              ON ST_Intersects(t.rast, a.geom_2926)
        )
        UPDATE assessor a
        SET aspect = a2.val
        FROM aspect_samples a2
        WHERE a.parcel_number = a2.parcel_number;

        ----------------------------------------------------------------------
        -- 6. Clean invalid aspect values
        ----------------------------------------------------------------------
        UPDATE assessor
        SET aspect = NULL
        WHERE aspect IS NOT NULL
          AND (aspect < 0 OR aspect >= 360);

        ----------------------------------------------------------------------
        -- 7. Compute aspect_dir classification (N, NE, E, SE, S, SW, W, NW)
        ----------------------------------------------------------------------
        UPDATE assessor
        SET aspect_dir = CASE
            WHEN aspect IS NULL THEN NULL
            WHEN aspect >= 337.5 OR aspect < 22.5  THEN 'N'
            WHEN aspect >= 22.5  AND aspect < 67.5  THEN 'NE'
            WHEN aspect >= 67.5  AND aspect < 112.5 THEN 'E'
            WHEN aspect >= 112.5 AND aspect < 157.5 THEN 'SE'
            WHEN aspect >= 157.5 AND aspect < 202.5 THEN 'S'
            WHEN aspect >= 202.5 AND aspect < 247.5 THEN 'SW'
            WHEN aspect >= 247.5 AND aspect < 292.5 THEN 'W'
            WHEN aspect >= 292.5 AND aspect < 337.5 THEN 'NW'
        END;

        ANALYZE assessor;

        """

        with connection.cursor() as cursor:
            cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS("Terrain rebuild complete — slope, aspect, and aspect_dir updated."))

