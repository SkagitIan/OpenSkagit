import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection

MANIFEST = Path("/home/django/django_project/data/property_tax_manifest.json")
TARGET_TABLE = "reference_tax_district"

EXCLUDE_TYPES = {"tca2025"}  # explicit and intentional


class Command(BaseCommand):
    help = "Normalize raw property tax district tables into one canonical table"

    def handle(self, *args, **options):
        if not MANIFEST.exists():
            raise RuntimeError(f"Manifest not found: {MANIFEST}")

        manifest = json.loads(MANIFEST.read_text())

        self.stdout.write("→ Creating canonical table")
        self.create_table()

        for dataset in manifest["datasets"]:
            dtype = dataset["district_type"]

            if dtype in EXCLUDE_TYPES:
                self.stdout.write(f"  - Skipping {dtype}")
                continue

            raw_table = dataset["table"]
            district_type = self.normalize_type(dtype)

            self.stdout.write(f"→ Ingesting {raw_table}")
            self.insert_from_raw(raw_table, district_type)

        self.stdout.write(self.style.SUCCESS("✓ Normalization complete"))

    def create_table(self):
        with connection.cursor() as cur:
            cur.execute(f"""
                DROP TABLE IF EXISTS {TARGET_TABLE};
                CREATE TABLE {TARGET_TABLE} (
                    id SERIAL PRIMARY KEY,
                    district_type TEXT NOT NULL,
                    district_code TEXT NOT NULL,
                    district_name TEXT,
                    county_name TEXT,
                    county_num INTEGER,
                    geom GEOMETRY(MULTIPOLYGON, 2926)
                );
            """)
            cur.execute(f"""
                CREATE INDEX ON {TARGET_TABLE} USING GIST (geom);
                CREATE INDEX ON {TARGET_TABLE} (district_type, district_code);
            """)

    def insert_from_raw(self, raw_table: str, district_type: str):
        with connection.cursor() as cur:
            cur.execute(f"""

                INSERT INTO {TARGET_TABLE} (
                    district_type,
                    district_code,
                    district_name,
                    county_name,
                    county_num,
                    geom
                )
                SELECT
                    %s                                  AS district_type,
                    DISTATTRIB                          AS district_code,
                    DESCRIPTIO                          AS district_name,
                    COUNTYNAME                          AS county_name,
                    COUNTYNUM::INTEGER                  AS county_num,
                    ST_Multi(geom)                      AS geom
                FROM {raw_table}
                WHERE geom IS NOT NULL;
            """, [district_type])

    def normalize_type(self, raw: str) -> str:
        """
        Collapse file-based names into stable district types.
        This is intentionally conservative.
        """
        raw = raw.lower()

        if raw.startswith("fir"):
            return "fire"
        if raw.startswith("ems"):
            return "ems"
        if raw.startswith("hsp"):
            return "hospital"
        if raw.startswith("lib"):
            return "library"
        if raw.startswith("prt"):
            return "port"
        if raw.startswith("pkr"):
            return "park"
        if raw.startswith("cem"):
            return "cemetery"
        if raw.startswith("sch"):
            return "school"
        if raw.startswith("pud"):
            return "pud"
        if raw.startswith("ptcty"):
            return "city"
        if raw.startswith("wat"):
            return "water"
        if raw.startswith("sew"):
            return "sewer"

        return raw
