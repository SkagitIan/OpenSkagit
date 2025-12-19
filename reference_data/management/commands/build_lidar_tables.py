from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Polygon
from django.db import connection
from openskagit.models import LidarTile, MasterParcel
from django.contrib.gis.db.models.aggregates import Extent


TILE_SIZE = 1000  # meters → perfect for Skagit


class Command(BaseCommand):
    help = "Builds a 1000m tile grid over Skagit County (SRID 2926) and maps parcels to tiles."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Starting LIDAR tile build..."))

        # 1. Compute county bounding box from parcel geometries
        extent = MasterParcel.objects.aggregate(extent=Extent("geometry__geom_2926"))["extent"]

        if not extent:
            self.stdout.write(self.style.ERROR("No parcel geometry found in DB."))
            return

        minx, miny, maxx, maxy = extent
        self.stdout.write(f"Parcel extent: {extent}")

        # 2. Build the tile grid
        tiles_to_create = []
        x = minx
        while x < maxx:
            y = miny
            while y < maxy:
                tile_geom = Polygon.from_bbox((x, y, x + TILE_SIZE, y + TILE_SIZE))
                tiles_to_create.append(LidarTile(geom=tile_geom))
                y += TILE_SIZE
            x += TILE_SIZE

        LidarTile.objects.all().delete()  # wipe old grid
        LidarTile.objects.bulk_create(tiles_to_create)

        self.stdout.write(self.style.SUCCESS(f"Created {len(tiles_to_create)} tiles."))

        # 3. Spatially map parcels → tiles
        self.stdout.write("Linking parcels to tiles (PostGIS spatial join)...")

        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO openskagit_lidartile_parcels (lidartile_id, masterparcel_id)
                SELECT DISTINCT tile_id, parcel_id
                FROM (
                    SELECT 
                        t.id AS tile_id,
                        p.parcel_number AS parcel_id
                    FROM openskagit_lidartile t
                    JOIN openskagit_parcelgeometry pg
                    ON ST_Intersects(pg.geom_2926, t.geom)
                    JOIN master_parcel p
                    ON p.parcel_number = pg.parcel_id
                ) sub;
            """)


        self.stdout.write(self.style.SUCCESS("Parcel → tile mapping complete."))
        self.stdout.write(self.style.SUCCESS("LIDAR tile grid build finished."))
