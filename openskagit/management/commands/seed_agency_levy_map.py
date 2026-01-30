import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from openskagit.models import AgencyLevyMap


class Command(BaseCommand):
    help = "Seed agency levy mappings from a CSV or JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            required=True,
            help="Path to CSV or JSON file with tdcode → MCAG mappings",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing mappings before import",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["input"])
        truncate = options["truncate"]

        if not path.exists():
            raise CommandError(f"File not found: {path}")

        if truncate:
            self.stdout.write("→ Deleting existing agency levy mappings")
            AgencyLevyMap.objects.all().delete()

        rows = self._load_rows(path)
        if not rows:
            raise CommandError("No rows found in input file.")

        created = 0
        updated = 0

        for row in rows:
            tdcode = (row.get("tdcode") or "").strip()
            mcag = (row.get("mcag") or "").strip()
            if not tdcode or not mcag:
                continue

            obj, was_created = AgencyLevyMap.objects.update_or_create(
                tdcode=tdcode,
                mcag=mcag,
                defaults={
                    "agency_name": (row.get("agency_name") or "").strip(),
                    "agency_type": (row.get("agency_type") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "is_primary": self._to_bool(row.get("is_primary"), default=True),
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"✓ Seed complete — created: {created}, updated: {updated}"
        ))

    def _load_rows(self, path: Path):
        suffix = path.suffix.lower()
        if suffix in {".csv"}:
            return self._load_csv(path)
        if suffix in {".json"}:
            return self._load_json(path)
        raise CommandError("Unsupported file type. Use .csv or .json")

    def _load_csv(self, path: Path):
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return list(reader)

    def _load_json(self, path: Path):
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        raise CommandError("JSON must be an object or list of objects.")

    def _to_bool(self, value, default=True):
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "t", "yes", "y"}:
            return True
        if text in {"0", "false", "f", "no", "n"}:
            return False
        return default
