import json
from pathlib import Path
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import TaxingDistrictLevy


def to_decimal(val):
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


class Command(BaseCommand):
    help = "Import TDCODE levy data from a JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            required=True,
            help="Path to tdcode.json file"
        )
        parser.add_argument(
            "--year",
            type=int,
            default=2024,
            help="Assessment year (default: 2024)"
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing rows for this assessment year before import"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["input"])
        year = options["year"]
        truncate = options["truncate"]

        if not path.exists():
            raise SystemExit(f"File not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Allow single-object JSON
        if isinstance(data, dict):
            data = [data]

        if truncate:
            self.stdout.write(f"→ Deleting existing rows for {year}")
            TaxingDistrictLevy.objects.filter(
                assessment_year=year
            ).delete()

        created = 0
        updated = 0

        self.stdout.write(f"→ Importing {len(data)} rows")

        for row in data:
            obj, was_created = TaxingDistrictLevy.objects.update_or_create(
                tdcode=row["tdcode"],
                assessment_year=year,
                defaults={
                    "district_name": row.get("district_name"),
                    "locally_assessed_value": row.get("locally_assessed_value"),
                    "levy_rate": to_decimal(row.get("levy_rate")),
                    "district_levy": row.get("district_levy"),
                    "highest_prior_levy": row.get("highest_prior_levy"),
                    "new_construction_assessed_value": row.get("new_construction_assessed_value"),
                    "levy_rate_2024": to_decimal(row.get("levy_rate_2024")),
                    "state_assessed_property_2024": row.get("state_assessed_property_2024"),
                    "state_assessed_property_2023": row.get("state_assessed_property_2023"),
                    "annexation_assessed_value_2023": row.get("annexation_assessed_value_2023"),
                    "annex_tax_due_2023": row.get("annex_tax_due_2023"),
                    "refund_tax_due_2023": row.get("refund_tax_due_2023"),
                    "max_allowable_levy": row.get("max_allowable_levy"),
                    "statutory_max_rate": to_decimal(row.get("statutory_max_rate")),
                    "levy_limit_percent_increase": to_decimal(row.get("levy_limit_percent_increase")),
                }
            )

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"✓ Import complete — created: {created}, updated: {updated}"
        ))
