import json
import numpy as np
import pdal
from datetime import datetime

from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Polygon
from django.contrib.gis.db.models.aggregates import Extent
from django.db import connection

from openskagit.models import LidarTile, MasterParcel, ParcelLidarStats


EPT_URL = (
    "https://usgs-lidar-public.s3.amazonaws.com/"
    "USGS_LPC_WA_MtBaker_2015_LAS_2017/ept.json"
)

class Command(BaseCommand):

    help = "Processes LiDAR tile-by-tile instead of parcel-by-parcel (MUCH FASTER)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tile", type=int, default=None,
            help="Process only a specific tile ID"
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Number of unprocessed tiles to run"
        )

    def handle(self, *args, **options):

        tile_id = options["tile"]
        limit = options["limit"]

        if tile_id:
            tiles = LidarTile.objects.filter(id=tile_id)
        else:
            tiles = LidarTile.objects.filter(last_processed__isnull=True)
            if limit:
                tiles = tiles.order_by("id")[:limit]

        if not tiles.exists():
            self.stdout.write(self.style.WARNING("No tiles to process."))
            return

        for tile in tiles:
            self.process_tile(tile)

        self.stdout.write(self.style.SUCCESS("Done."))

    # ----------------------------------------------------
    # PROCESS 1 TILE
    # ----------------------------------------------------
    def process_tile(self, tile: LidarTile):

        t_minx, t_miny, t_maxx, t_maxy = tile.geom.extent

        # USGS requires fetch bounds in Web Mercator (EPSG:3857)
        # ---- REPROJECTION ----
        # (We do a simple GEOS transform — geometry is small, no problem.)
        tile_3857 = tile.geom.transform(3857, clone=True)
        b_minx, b_miny, b_maxx, b_maxy = tile_3857.extent

        bounds_str = f"([{b_minx}, {b_maxx}], [{b_miny}, {b_maxy}])"

        pipeline_json = {
            "pipeline": [
                {
                    "type": "readers.ept",
                    "filename": EPT_URL,
                    "bounds": bounds_str,
                    "resolution": 1.0
                },
                {
                    "type": "filters.reprojection",
                    "in_srs": "EPSG:3857",
                    "out_srs": "EPSG:2926"
                }
            ]
        }

        self.stdout.write(f"\nProcessing tile {tile.id} …")
        self.stdout.write(f"Bounds: {bounds_str}")

        try:
            pipeline = pdal.Pipeline(json.dumps(pipeline_json))
            pipeline.execute()
            
            arr = pipeline.arrays[0]
            # Add this to your management command after pipeline.execute()

            self.stdout.write(f"PDAL returned {len(arr)} points")
            if len(arr) > 0:
                self.stdout.write(f"Sample point: X={arr['X'][0]}, Y={arr['Y'][0]}, Z={arr['Z'][0]}")
                self.stdout.write(f"X range: {arr['X'].min()} to {arr['X'].max()}")
                self.stdout.write(f"Y range: {arr['Y'].min()} to {arr['Y'].max()}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"PDAL failed for tile {tile.id}: {e}"))
            return

        # Extract numpy arrays
        pts_x = arr["X"]
        pts_y = arr["Y"]
        pts_z = arr["Z"]

        pts = np.column_stack((pts_x, pts_y, pts_z))

        # ----------------------------------------------------
        # GET PARCELS INSIDE THIS TILE
        # ----------------------------------------------------
        parcels = tile.parcels.all()

        if not parcels:
            self.stdout.write("Tile has no parcels. Marking as processed.")
            tile.last_processed = datetime.utcnow()
            tile.save(update_fields=["last_processed"])
            return

        # ----------------------------------------------------
        # CLIP → COMPUTE LIDAR STATS
        # ----------------------------------------------------
        processed = 0

        for parcel in parcels:

            p_minx, p_miny, p_maxx, p_maxy = parcel.geometry.geom_2926.extent

            mask = (
                (pts_x >= p_minx) & (pts_x <= p_maxx) &
                (pts_y >= p_miny) & (pts_y <= p_maxy)
            )

            pz = pts_z = pts[mask][:, 2]  # get only Z values

            if len(pz) == 0:
                continue

            # ---- CALCULATE ----
            min_z = float(np.min(pz))
            max_z = float(np.max(pz))
            mean_z = float(np.mean(pz))
            std_z = float(np.std(pz))

            to_ft = 3.28084

            ParcelLidarStats.objects.update_or_create(
                parcel=parcel,
                defaults={
                    "min_elevation_ft": min_z * to_ft,
                    "max_elevation_ft": max_z * to_ft,
                    "mean_terrain_z_ft": mean_z * to_ft,
                    "terrain_roughness": std_z,
                    "est_canopy_height_ft": (max_z - mean_z) * to_ft,
                    "point_density_sqft": len(pz) / parcel.geometry.geom_2926.area,
                }
            )

            processed += 1

        tile.last_processed = datetime.utcnow()
        tile.save(update_fields=["last_processed"])

        self.stdout.write(self.style.SUCCESS(
            f"Tile {tile.id}: processed {processed} parcels"
        ))
