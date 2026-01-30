import json
from typing import List

from django.conf import settings
from django.core.management.base import BaseCommand

from openskagit.models import ParcelHistory
from openskagit.tax import _compute_county_etr_insights, _coerce_history_rows, _extract_history_year


class Command(BaseCommand):
    help = "Build a cached county ETR snapshot JSON for fast API reads."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, action="append", help="Tax year to compute (repeatable).")
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Override output path (default: data/county_etr_stats.json).",
        )

    def handle(self, *args, **options):
        years = options.get("year") or []
        if not years:
            years = self._discover_years()
        if not years:
            self.stdout.write(self.style.WARNING("No parcel history years found."))
            return

        payload = {}
        for year in sorted(set(years)):
            result = _compute_county_etr_insights(year)
            if result is None:
                continue
            payload[str(year)] = result

        output_path = options.get("output")
        if output_path:
            path = output_path
        else:
            path = f"{settings.BASE_DIR}/data/county_etr_stats.json"

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

        self.stdout.write(self.style.SUCCESS(f"Wrote county ETR snapshot to {path}"))  # pragma: no cover

    def _discover_years(self) -> List[int]:
        years = set()
        for record in ParcelHistory.objects.only("rows").iterator():
            rows = _coerce_history_rows(record.rows)
            if not rows:
                continue
            for row in rows:
                year = _extract_history_year(row)
                if year is not None:
                    years.add(year)
        return sorted(years)
