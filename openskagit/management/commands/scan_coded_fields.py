from django.core.management.base import BaseCommand
from django.db import connection
import csv
from pathlib import Path

# define which text fields to inspect per table
TEXT_FIELDS = {
    "assessor": [
        "building_style", "foundation", "exterior_walls", "roof_covering",
        "roof_style", "floor_covering", "floor_construction", "interior_finish",
        "heat_air_cond", "fireplace", "property_type", "sale_deed_type",
        "fire_district", "school_district", "city_district", "levy_code",
        "has_septic"
    ],
    "improvements": [
        "building_style", "construction_style", "foundation", "exterior_wall",
        "roof_covering", "roof_style", "flooring", "floor_construction",
        "interior_finish", "plumbing_code", "appliances", "heating_cooling",
        "fireplace", "condition_code", "comment"
    ],
    "land": [
        "land_type", "appraisal_method", "open_space_appraisal_method",
        "land_segment_comment"
    ],
    "sales": [
        "sale_type", "deed_type"
    ],
}

class Command(BaseCommand):
    help = "Scan text fields in assessor/improvements/land/sales for distinct coded values."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="Limit distinct values per column.")

    def handle(self, *args, **opts):
        out = Path("coded_fields_scan.csv")
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["table", "column", "distinct_count", "sample_values"])
            for table, cols in TEXT_FIELDS.items():
                for col in cols:
                    sql = f"""
                        SELECT DISTINCT TRIM({col})
                        FROM {table}
                        WHERE {col} IS NOT NULL
                          AND TRIM({col}) <> ''
                        LIMIT {opts['limit']};
                    """
                    with connection.cursor() as cur:
                        cur.execute(sql)
                        vals = [v[0] for v in cur.fetchall() if v[0]]
                    if vals:
                        writer.writerow([table, col, len(vals), "; ".join(map(str, vals))])
        self.stdout.write(self.style.SUCCESS(f"Wrote scan results to {out.resolve()}"))
