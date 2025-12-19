import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import ZoningRule


SKAGIT_DEFAULTS = {
    "min_lot_size_sqft": 43560,
    "max_lot_coverage_pct": 35,
    "max_height_ft": 30,
    "front_setback_ft": 35,
    "side_setback_ft": 8,
    "rear_setback_ft": 25,
    "allows_adu": True,
    "allows_duplex": False,
    "allows_multifamily": False,
}


class Command(BaseCommand):
    help = "Load zoning rules from CSV and fill UNKNOWN values using Skagit County defaults."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            type=str,
            help="Path to zoning_rules.csv"
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"])
        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f"CSV not found: {csv_path}"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Loading zoning rules…"))

        with csv_path.open("r", newline="", encoding="utf-8") as f, transaction.atomic():
            reader = csv.DictReader(f)

            for row in reader:
                zone_code = row["zone_code"].strip()
                jurisdiction = row["jurisdiction"].strip()

                # Convert CSV "UNKNOWN" → None
                def clean(val):
                    if val is None:
                        return None
                    s = str(val).strip().upper()
                    if s in ("", "NONE", "NULL", "UNKNOWN"):
                        return None
                    return val

                record = {
                    "min_lot_size_sqft": clean(row["min_lot_size_sqft"]),
                    "max_lot_coverage_pct": clean(row["max_lot_coverage_pct"]),
                    "max_height_ft": clean(row["max_height_ft"]),
                    "front_setback_ft": clean(row["front_setback_ft"]),
                    "side_setback_ft": clean(row["side_setback_ft"]),
                    "rear_setback_ft": clean(row["rear_setback_ft"]),
                    "allows_adu": clean(row["allows_adu"]),
                    "allows_duplex": clean(row["allows_duplex"]),
                    "allows_multifamily": clean(row["allows_multifamily"]),
                }

                # Fill missing values with Skagit County defaults
                for field, default_val in SKAGIT_DEFAULTS.items():
                    if record[field] is None:
                        record[field] = default_val

                # Convert boolean strings
                for bool_field in ["allows_adu", "allows_duplex", "allows_multifamily"]:
                    v = record[bool_field]
                    if isinstance(v, str):
                        record[bool_field] = v.strip().upper() in ("TRUE", "T", "YES", "1")

                zr, created = ZoningRule.objects.update_or_create(
                    zone_code=zone_code,
                    jurisdiction=jurisdiction,
                    defaults=record
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created: {jurisdiction} - {zone_code}"))
                else:
                    self.stdout.write(f"Updated: {jurisdiction} - {zone_code}")

        self.stdout.write(self.style.SUCCESS("Zoning rules loaded successfully."))
