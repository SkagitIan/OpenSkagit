from django.core.management.base import BaseCommand
from django.contrib.gis.db.models import Union
from django.contrib.gis.geos import MultiPolygon, Polygon, GEOSGeometry

from openskagit.models import Assessor, NeighborhoodGeom


class Command(BaseCommand):
    help = "Precalculate union geometry for each neighborhood (small hood)."

    def handle(self, *args, **options):
        self.stdout.write("Rebuilding NeighborhoodGeom table…")
        NeighborhoodGeom.objects.all().delete()

        qs = (
            Assessor.objects
            .exclude(geom__isnull=True)
            .values("neighborhood_code")
            .annotate(geom_union=Union("geom"))
        )

        count = 0
        for row in qs:
            code = row["neighborhood_code"]
            union_geom = row["geom_union"]

            if not union_geom:
                continue

            # 1) Re-wrap union geometry and force SRID 3857
            g = GEOSGeometry(union_geom.wkb)
            g.srid = 3857  # SRID of Assessor.geom

            # 2) Build convex hull (can be Point/Line/Polygon)
            hull_3857 = g.convex_hull

            # 3) If not area, buffer to get a polygon
            if hull_3857.geom_type in ("Point", "MultiPoint", "LineString", "MultiLineString"):
                hull_3857 = hull_3857.buffer(25)  # ~25m around it; tweak if needed

            # 4) Ensure Polygon → MultiPolygon
            if isinstance(hull_3857, Polygon):
                hull_3857 = MultiPolygon(hull_3857)

            # 5) Force SRID again on final hull
            hull_3857.srid = 3857

            # 6) Transform for Leaflet (returns a NEW geometry)
            hull_4326 = hull_3857.transform(4326, clone=True)

            NeighborhoodGeom.objects.create(
                code=code,
                geom_3857=hull_3857,
                geom_4326=hull_4326,
            )
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Built {count} neighborhood geoms."))