from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = (
        "Rebuild openskagit_parcelgeometry from reference_parcels and compute distance metrics."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding ParcelGeometry..."))

        truncate_sql = "TRUNCATE TABLE openskagit_parcelgeometry RESTART IDENTITY;"

        insert_sql = """
        WITH base AS (
            SELECT DISTINCT ON (rp."PARCELID")
                rp."PARCELID"::text AS parcel_id,
                rp.geometry AS geom
            FROM reference_parcels rp
            WHERE rp."PARCELID" IS NOT NULL
              AND rp.geometry IS NOT NULL
              AND NOT ST_IsEmpty(rp.geometry)
            ORDER BY rp."PARCELID", ST_Area(rp.geometry) DESC
        ),
        normalized AS (
            SELECT
                parcel_id,
                ST_Multi(geom)::geometry(MULTIPOLYGON, 2926) AS geom_2926_raw,
                ST_Multi(
                    ST_CollectionExtract(
                        ST_MakeValid(geom),
                        3
                    )
                )::geometry(MULTIPOLYGON, 2926) AS geom_2926_valid_raw
            FROM base
        ),
        cleaned AS (
            SELECT
                parcel_id,
                geom_2926_raw,
                CASE
                    WHEN geom_2926_valid_raw IS NULL OR ST_IsEmpty(geom_2926_valid_raw)
                        THEN NULL
                    ELSE geom_2926_valid_raw
                END AS geom_2926_valid
            FROM normalized
        ),
        centroids AS (
            SELECT
                parcel_id,
                COALESCE(geom_2926_valid, geom_2926_raw) AS geom_2926,
                geom_2926_valid,
                ST_Centroid(COALESCE(geom_2926_valid, geom_2926_raw)) AS centroid_2926
            FROM cleaned
        ),
        centroids_4326 AS (
            SELECT
                parcel_id,
                geom_2926,
                geom_2926_valid,
                centroid_2926,
                ST_Transform(centroid_2926, 4326) AS centroid_geog
            FROM centroids
        )
        INSERT INTO openskagit_parcelgeometry (
            parcel_id,
            geom_2926,
            geom_2926_valid,
            geom,
            geom_backup,
            centroid_2926,
            centroid_geog,
            latitude,
            longitude,
            dist_major_road,
            dist_minor_road,
            dist_floodway,
            dist_city_center,
            dist_school,
            dist_park,
            dist_supermarket,
            dist_hospital,
            dist_fire_station
        )
        SELECT
            c.parcel_id,
            c.geom_2926,
            c.geom_2926_valid,
            ST_Transform(c.geom_2926, 3857) AS geom,
            ST_Transform(c.geom_2926, 3857) AS geom_backup,
            c.centroid_2926,
            c.centroid_geog::geometry(Point, 4326) AS centroid_geog,
            ST_Y(c.centroid_geog) AS latitude,
            ST_X(c.centroid_geog) AS longitude,
            r_major.dist,
            r_minor.dist,
            fw.dist,
            city.dist,
            sch.dist,
            park.dist,
            smkt.dist,
            hosp.dist,
            fire.dist
        FROM centroids_4326 c
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, r.geom_2926) AS dist
            FROM osm.planet_osm_roads r
            WHERE r.highway IN ('motorway','trunk','primary','secondary')
            ORDER BY c.geom_2926 <-> r.geom_2926
            LIMIT 1
        ) r_major ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, r.geom_2926) AS dist
            FROM osm.planet_osm_roads r
            WHERE r.highway IN ('residential','unclassified','service','tertiary')
            ORDER BY c.geom_2926 <-> r.geom_2926
            LIMIT 1
        ) r_minor ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, ST_Transform(f.wkb_geometry, 2926)) AS dist
            FROM public.floodway_skagit f
            ORDER BY c.geom_2926 <-> ST_Transform(f.wkb_geometry, 2926)
            LIMIT 1
        ) fw ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.place IN ('city','town','village','hamlet','suburb')
            ORDER BY c.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) city ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.amenity = 'school'
            ORDER BY c.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) sch ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_polygon p
            WHERE p.leisure = 'park'
               OR p.landuse = 'recreation_ground'
            ORDER BY c.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) park ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.shop IN ('supermarket','grocery','convenience')
            ORDER BY c.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) smkt ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.amenity IN ('hospital','clinic')
            ORDER BY c.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) hosp ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Distance(c.geom_2926, p.geom_2926) AS dist
            FROM osm.planet_osm_point p
            WHERE p.amenity = 'fire_station'
            ORDER BY c.geom_2926 <-> p.geom_2926
            LIMIT 1
        ) fire ON TRUE;
        """

        with transaction.atomic(), connection.cursor() as cursor:
            self.stdout.write("Truncating openskagit_parcelgeometry...")
            cursor.execute(truncate_sql)

            self.stdout.write("Inserting rebuilt parcel geometry + distances...")
            cursor.execute(insert_sql)
            inserted = cursor.rowcount

        self.stdout.write(
            self.style.SUCCESS(
                f"ParcelGeometry rebuilt for {inserted:,} parcels."
            )
        )
