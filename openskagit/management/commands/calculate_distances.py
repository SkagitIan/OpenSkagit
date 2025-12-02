import sys
from django.core.management.base import BaseCommand
from django.db import connection
from openskagit.models import Assessor, AssessmentRoll


class Command(BaseCommand):
    help = "Compute OSM-based distance metrics using high-performance LATERAL KNN joins."

    def handle(self, *args, **options):
        assessor_table = Assessor._meta.db_table
        roll_table = AssessmentRoll._meta.db_table

        self.stdout.write(self.style.SUCCESS(f"Using assessor table: {assessor_table}"))
        self.stdout.write(self.style.SUCCESS(f"Using roll table: {roll_table}"))

        sql = f"""
        DROP TABLE IF EXISTS assessor_distances;

        CREATE TABLE assessor_distances (
            parcel_number TEXT PRIMARY KEY,
            dist_major_road FLOAT,
            dist_minor_road FLOAT,
            dist_floodway FLOAT,
            dist_city_center FLOAT,
            dist_school FLOAT,
            dist_park FLOAT,
            dist_supermarket FLOAT,
            dist_hospital FLOAT,
            dist_fire_station FLOAT,
            dist_trailhead FLOAT
        );

        INSERT INTO assessor_distances (
            parcel_number,
            dist_major_road,
            dist_minor_road,
            dist_floodway,
            dist_city_center,
            dist_school,
            dist_park,
            dist_supermarket,
            dist_hospital,
            dist_fire_station,
            dist_trailhead
        )
        SELECT
            a.parcel_number,

            r_major.dist,
            r_minor.dist,
            fw.dist,
            city.dist,
            sch.dist,
            park.dist,
            smkt.dist,
            hosp.dist,
            fire.dist,
            trail.dist

        FROM {assessor_table} a

        ----------------------------------------------------------
        -- LATERAL JOINS – using geom_2926 (FAST)
        ----------------------------------------------------------

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, r.geom_2926) AS dist
            FROM osm.planet_osm_roads r
            WHERE r.highway IN ('motorway','trunk','primary','secondary')
            ORDER BY a.geom_2926 <-> r.geom_2926
            LIMIT 1
        ) r_major ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, r.geom_2926) AS dist
            FROM osm.planet_osm_roads r
            WHERE r.highway IN ('residential','unclassified','service','tertiary')
            ORDER BY a.geom_2926 <-> r.geom_2926
            LIMIT 1
        ) r_minor ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, ST_Transform(f.wkb_geometry,2926)) AS dist
            FROM public.floodway_skagit f
            ORDER BY a.geom_2926 <-> ST_Transform(f.wkb_geometry,2926)
            LIMIT 1
        ) fw ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.place IN ('city','town','village','hamlet','suburb')
            ORDER BY a.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) city ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.amenity = 'school'
            ORDER BY a.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) sch ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, pg.geom_2926) AS dist
            FROM osm.planet_osm_polygon pg
            WHERE pg.leisure = 'park'
               OR pg.landuse = 'recreation_ground'
            ORDER BY a.geom_2926 <-> pg.geom_2926
            LIMIT 1
        ) park ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.shop IN ('supermarket','grocery','convenience')
            ORDER BY a.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) smkt ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.amenity IN ('hospital','clinic')
            ORDER BY a.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) hosp ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.amenity = 'fire_station'
            ORDER BY a.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) fire ON TRUE

        LEFT JOIN LATERAL (
            SELECT ST_Distance(a.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.tourism = 'trailhead'
            ORDER BY a.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) trail ON TRUE

        WHERE a.roll_id IN (SELECT id FROM {roll_table} WHERE year = 2025);

        UPDATE {assessor_table} a
        SET
            dist_major_road   = d.dist_major_road,
            dist_minor_road   = d.dist_minor_road,
            dist_floodway     = d.dist_floodway,
            dist_city_center  = d.dist_city_center,
            dist_school       = d.dist_school,
            dist_park         = d.dist_park,
            dist_supermarket  = d.dist_supermarket,
            dist_hospital     = d.dist_hospital,
            dist_fire_station = d.dist_fire_station,
            dist_trailhead    = d.dist_trailhead
        FROM assessor_distances d
        WHERE a.parcel_number = d.parcel_number
          AND a.roll_id IN (SELECT id FROM {roll_table} WHERE year = 2025);
        """

        with connection.cursor() as cursor:
            self.stdout.write(self.style.WARNING("Starting distance calculations..."))
            cursor.execute(sql)
            self.stdout.write(self.style.SUCCESS("Distances computed using high-performance LATERAL joins."))
