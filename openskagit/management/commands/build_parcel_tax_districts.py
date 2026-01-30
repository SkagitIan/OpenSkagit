from django.core.management.base import BaseCommand
from django.db import connection


PARCEL_TABLE = "openskagit_parcelgeometry"
PARCEL_ID_COL = "parcel_id"
PARCEL_GEOM_COL = "geom_2926"

DISTRICT_TABLE = "reference_tax_district"
DISTRICT_GEOM_COL = "geom"

OUTPUT_TABLE = "parcel_tax_district"


class Command(BaseCommand):
    help = "Build parcel → tax district intersection table"

    def handle(self, *args, **options):
        self.stdout.write("→ Building parcel_tax_district")

        with connection.cursor() as cur:
            # Drop + create
            cur.execute(f"""
                DROP TABLE IF EXISTS {OUTPUT_TABLE};
                CREATE TABLE {OUTPUT_TABLE} (
                    parcel_id TEXT NOT NULL,
                    district_type TEXT NOT NULL,
                    district_code TEXT NOT NULL
                );
            """)

            # Spatial join (county-scoped)
            self.stdout.write("→ Running spatial join")
            cur.execute(f"""
                INSERT INTO parcel_tax_district (
                    parcel_id,
                    district_type,
                    district_code
                )
                SELECT DISTINCT
                    p.parcel_id,
                    d.district_type,
                    d.district_code
                FROM openskagit_parcelgeometry p
                JOIN reference_tax_district d
                ON ST_Intersects(p.geom_2926, d.geom)
                WHERE d.county_name = 'SKAGIT';

            """)

            # Indexes
            self.stdout.write("→ Creating indexes")
            cur.execute(f"""
                CREATE INDEX ON {OUTPUT_TABLE} (parcel_id);
                CREATE INDEX ON {OUTPUT_TABLE} (district_type, district_code);
            """)

        self.stdout.write(self.style.SUCCESS("✓ parcel_tax_district built"))
