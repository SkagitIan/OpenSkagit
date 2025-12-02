from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Prepare OSM tables for fast distance calculations (geom_2926 + GiST indexes)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Preparing OSM tables..."))

        sql = """
        CREATE EXTENSION IF NOT EXISTS postgis;

        --------------------------
        -- Helper procedure
        --------------------------
        DO $$
        DECLARE 
            rec record;
        BEGIN
            FOR rec IN
                SELECT 'osm.planet_osm_point'   AS tbl, 'POINT'      AS gtype UNION ALL
                SELECT 'osm.planet_osm_polygon' AS tbl, 'GEOMETRY'   AS gtype UNION ALL
                SELECT 'osm.planet_osm_line'    AS tbl, 'LINESTRING' AS gtype UNION ALL
                SELECT 'osm.planet_osm_roads'   AS tbl, 'LINESTRING' AS gtype
            LOOP
                RAISE NOTICE 'Processing %', rec.tbl;

                -- Add geom_2926 column
                EXECUTE format(
                    'ALTER TABLE %s ADD COLUMN IF NOT EXISTS geom_2926 geometry(%s,2926);',
                    rec.tbl, rec.gtype
                );

                -- Populate geom_2926
                EXECUTE format(
                    'UPDATE %s SET geom_2926 = ST_Transform(way,2926)
                     WHERE geom_2926 IS NULL AND way IS NOT NULL;',
                    rec.tbl
                );

                -- Create GiST index
                EXECUTE format(
                    'CREATE INDEX IF NOT EXISTS %s_geom_2926_gix
                     ON %s USING gist (geom_2926);',
                    replace(split_part(rec.tbl,'.',2), '"',''), rec.tbl
                );
            END LOOP;
        END$$;

        ANALYZE osm.planet_osm_point;
        ANALYZE osm.planet_osm_polygon;
        ANALYZE osm.planet_osm_line;
        ANALYZE osm.planet_osm_roads;
        """

        with connection.cursor() as cursor:
            cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS("OSM tables prepared successfully."))
