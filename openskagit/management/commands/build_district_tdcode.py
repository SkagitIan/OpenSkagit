import re
from django.core.management.base import BaseCommand
from django.db import connection


SOURCE_TABLE = "taxing_district_levy"
TARGET_TABLE = "district_tdcode"


TYPE_MAP = {
    "FIRE": "fire",
    "EMS": "ems",
    "HOSPITAL": "hospital",
    "LIBRARY": "library",
    "CEMETERY": "cemetery",
    "PARK": "park",
    "PORT": "port",
    "PUD": "pud",
    "SEWER": "sewer",
    "SCHOOL": "school",
}


class Command(BaseCommand):
    help = "Build district → TDCODE crosswalk from taxing_district_levy"

    def handle(self, *args, **options):
        self.stdout.write("→ Building district_tdcode")

        with connection.cursor() as cur:
            cur.execute(f"""
                DROP TABLE IF EXISTS {TARGET_TABLE};
                CREATE TABLE {TARGET_TABLE} (
                    district_type TEXT,
                    district_code TEXT,
                    tdcode TEXT NOT NULL,
                    assessment_year INTEGER NOT NULL
                );
            """)

            cur.execute(f"""
                SELECT tdcode, district_name, assessment_year
                FROM {SOURCE_TABLE}
            """)
            rows = cur.fetchall()

            inserts = []

            for tdcode, name, year in rows:
                upper = name.upper()

                # Countywide / state levies
                if upper.startswith("STATE SCHOOL") or upper.startswith("COUNTY"):
                    # Parcel join uses district_code = tdcode for countywide rows.
                    inserts.append(("countywide", tdcode, tdcode, year))
                    continue

                # Extract district number
                NON_SCHOOL_KEYWORDS = (
                    "FIRE",
                    "HOSPITAL",
                    "EMS",
                    "PORT",
                    "CEMETERY",
                    "PARK",
                    "PUD",
                    "SEWER",
                )

                # Extract district number
                m = re.search(r"#\s*(\d+)", upper)
                if not m:
                    continue

                # Keep unpadded codes to match reference_tax_district / parcel_tax_district.
                district_code = m.group(1)

                # School districts (must be enrichment/tech/bond AND not another district type)
                if (
                    any(k in upper for k in ("ENRICHMENT", "TECH", "BOND"))
                    and not any(k in upper for k in NON_SCHOOL_KEYWORDS)
                ):
                    inserts.append(("school", district_code, tdcode, year))
                    continue


                # Other district types
                district_type = None
                for key, dtype in TYPE_MAP.items():
                    if key in upper:
                        district_type = dtype
                        break

                if district_type:
                    inserts.append((district_type, district_code, tdcode, year))


            cur.executemany(
                f"""
                INSERT INTO {TARGET_TABLE}
                  (district_type, district_code, tdcode, assessment_year)
                VALUES (%s, %s, %s, %s)
                """,
                inserts
            )

            cur.execute(f"CREATE INDEX ON {TARGET_TABLE}(district_type, district_code);")
            cur.execute(f"CREATE INDEX ON {TARGET_TABLE}(tdcode);")

        self.stdout.write(self.style.SUCCESS(
            f"✓ district_tdcode built ({len(inserts)} rows)"
        ))
