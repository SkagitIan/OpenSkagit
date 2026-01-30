import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


SRC_DIR = Path("/home/django/django_project/data/property_tax_shp")
OUT_MANIFEST = Path("/home/django/django_project/data/property_tax_manifest.json")
TARGET_SRID = 2926

DB_CONN = (
    f"PG:dbname={settings.DATABASES['default']['NAME']} "
    f"user={settings.DATABASES['default']['USER']} "
    f"password={settings.DATABASES['default']['PASSWORD']} "
    f"host={settings.DATABASES['default']['HOST']}"
)


class Command(BaseCommand):
    help = "Ingest all property tax district shapefiles and emit a manifest"

    def handle(self, *args, **options):
        if not SRC_DIR.exists():
            raise CommandError(f"Source dir not found: {SRC_DIR}")

        manifest = {
            "srid": TARGET_SRID,
            "source_dir": str(SRC_DIR),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "datasets": [],
        }

        for zip_path in sorted(SRC_DIR.glob("*.zip")):
            self.stdout.write(f"→ Processing {zip_path.name}")
            dataset = self.process_zip(zip_path)
            manifest["datasets"].append(dataset)

        tmp = OUT_MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2))
        tmp.replace(OUT_MANIFEST)

        self.stdout.write(self.style.SUCCESS("✓ Ingestion complete"))
        self.stdout.write(f"Manifest written to {OUT_MANIFEST}")

    def process_zip(self, zip_path: Path) -> dict:
        district_type = zip_path.stem.lower()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            subprocess.run(
                ["unzip", "-q", str(zip_path), "-d", str(tmpdir)],
                check=True,
            )

            shps = list(tmpdir.glob("*.shp"))
            if len(shps) != 1:
                raise CommandError(f"{zip_path.name}: expected 1 .shp, found {len(shps)}")

            shp = shps[0]

            info = self.ogrinfo(shp)
            source_srid = info["srid"]
            fields = info["fields"]
            geom_type = info["geometry_type"]

            table = f"reference_{district_type}_district_raw"

            self.load_to_postgis(shp, table)

            stats = self.post_load_stats(table)

            return {
                "district_type": district_type,
                "zip_file": zip_path.name,
                "table": table,
                "geometry_type": geom_type,
                "source_srid": source_srid,
                "row_count": stats["row_count"],
                "fields": fields,
                "issues": {
                    "invalid_geometries": stats["invalid_geometries"],
                    "empty_geometries": stats["empty_geometries"],
                },
                "notes": [],
            }

    def ogrinfo(self, shp: Path) -> dict:
        cmd = ["ogrinfo", "-so", str(shp), Path(shp).stem]

        out = subprocess.check_output(cmd, text=True)

        fields = []
        geom_type = None
        srid = None

        for line in out.splitlines():
            line = line.strip()

            if line.startswith("Geometry:"):
                geom_type = line.split(":", 1)[1].strip()

            if "AUTHORITY" in line and "EPSG" in line:
                srid = int(line.split(",")[-1].strip("]\""))

            if ":" in line and "(" in line and ")" in line:
                name, rest = line.split(":", 1)
                ftype = rest.split("(")[0].strip()
                fields.append({"name": name.strip(), "type": ftype})

        return {
            "geometry_type": geom_type,
            "srid": srid,
            "fields": fields,
        }

    def load_to_postgis(self, shp: Path, table: str):
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            DB_CONN,
            str(shp),
            "-nln", table,
            "-nlt", "MULTIPOLYGON",
            "-t_srs", f"EPSG:{TARGET_SRID}",
            "-lco", "GEOMETRY_NAME=geom",
            "-lco", "FID=id",
            "-lco", "PRECISION=NO",
            "-overwrite",
        ]
        subprocess.run(cmd, check=True)

    def post_load_stats(self, table: str) -> dict:
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cur.fetchone()[0]

            cur.execute(
                f"""
                SELECT
                  COUNT(*) FILTER (WHERE NOT ST_IsValid(geom)),
                  COUNT(*) FILTER (WHERE ST_IsEmpty(geom))
                FROM {table}
                """
            )
            invalid, empty = cur.fetchone()

        return {
            "row_count": row_count,
            "invalid_geometries": invalid,
            "empty_geometries": empty,
        }
