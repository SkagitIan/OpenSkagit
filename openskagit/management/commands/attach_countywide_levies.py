from django.core.management.base import BaseCommand
from django.db import connection

OUTPUT_TABLE = "parcel_tax_district"
PARCEL_TABLE = "openskagit_parcelgeometry"
LEVY_TABLE = "taxing_district_levy"

ASSESSMENT_YEAR = 2024

COUNTYWIDE_TDCODES = [
    "290000000",
    "290000200",
    "290100000",
    "290101180",
    "290200100",
    "290200200",
]

class Command(BaseCommand):
    help = "Attach countywide/state levies to all parcels"

    def handle(self, *args, **options):
        self.stdout.write("→ Attaching countywide levies to parcels")

        with connection.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {OUTPUT_TABLE} (parcel_id, district_type, district_code)
                SELECT
                    p.parcel_id,
                    'countywide' AS district_type,
                    t.tdcode AS district_code
                FROM {PARCEL_TABLE} p
                JOIN (
                    SELECT DISTINCT tdcode
                    FROM {LEVY_TABLE}
                    WHERE assessment_year = {ASSESSMENT_YEAR}
                      AND tdcode IN ({",".join(f"'{c}'" for c in COUNTYWIDE_TDCODES)})
                ) t
                  ON TRUE
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM {OUTPUT_TABLE} x
                    WHERE x.parcel_id = p.parcel_id
                      AND x.district_type = 'countywide'
                      AND x.district_code = t.tdcode
                );
            """)

        self.stdout.write(self.style.SUCCESS("✓ Countywide levies attached"))
