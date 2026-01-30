import json
import re
from collections import defaultdict
from decimal import Decimal
from typing import Dict, Optional, Tuple

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from openskagit.models import MasterParcel, ParcelHistory


TOTAL_KEYS = (
    "Property Tax, Assessments, and Fees Total",
    "Total Due",
)


def _parse_money(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        return Decimal(text)
    except Exception:
        return None


def _extract_statement_year(summary: Dict[str, str]) -> Optional[int]:
    for key in summary.keys():
        match = re.search(r"(20\d{2})", str(key))
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _extract_total(summary: Dict[str, str]) -> Optional[Decimal]:
    for key, value in summary.items():
        for token in TOTAL_KEYS:
            if token in key:
                total = _parse_money(value)
                if total is not None:
                    return total
    return None


class Command(BaseCommand):
    help = "Build neighborhood tax totals from ParcelHistory.taxes summary payloads"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Limit number of parcels to scan")
        parser.add_argument("--dry-run", action="store_true", help="Compute but do not write to DB")

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]

        totals: Dict[Tuple[str, int], Dict[str, Decimal]] = defaultdict(lambda: {"total": Decimal("0"), "count": 0})

        qs = ParcelHistory.objects.exclude(taxes={}).only("parcel_number", "taxes", "neighborhood_code")
        if limit:
            qs = qs[:limit]

        batch_size = 1000
        batch = []

        for record in qs.iterator():
            batch.append(record)
            if len(batch) >= batch_size:
                self._process_batch(batch, totals)
                batch = []

        if batch:
            self._process_batch(batch, totals)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no changes written."))
            self.stdout.write(self.style.SUCCESS(f"Computed {len(totals)} neighborhood/year totals."))
            return

        self._write_totals(totals)
        self.stdout.write(self.style.SUCCESS(f"✓ Wrote {len(totals)} neighborhood/year totals."))

    def _process_batch(self, batch, totals):
        parcel_numbers = [r.parcel_number for r in batch]
        hood_map = {
            row.parcel_number: row.hood_code
            for row in MasterParcel.objects.filter(parcel_number__in=parcel_numbers).only("parcel_number", "hood_code")
        }

        for record in batch:
            taxes = record.taxes
            if isinstance(taxes, str):
                try:
                    taxes = json.loads(taxes)
                except Exception:
                    continue
            if not isinstance(taxes, dict):
                continue

            summary = taxes.get("summary") or {}
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except Exception:
                    summary = {}

            year = _extract_statement_year(summary)
            total = _extract_total(summary)
            if year is None or total is None:
                continue

            hood = record.neighborhood_code or hood_map.get(record.parcel_number)
            if not hood:
                continue

            key = (hood, year)
            totals[key]["total"] += total
            totals[key]["count"] += 1

    def _write_totals(self, totals):
        with connection.cursor() as cur:
            cur.execute(
                """
                DROP TABLE IF EXISTS hood_tax_totals;
                CREATE TABLE hood_tax_totals (
                    hood_code TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    total_tax NUMERIC NOT NULL,
                    parcel_count INTEGER NOT NULL
                );
                """
            )

            rows = [
                (hood, year, data["total"], data["count"])
                for (hood, year), data in totals.items()
            ]

            cur.executemany(
                """
                INSERT INTO hood_tax_totals (hood_code, tax_year, total_tax, parcel_count)
                VALUES (%s, %s, %s, %s)
                """,
                rows,
            )

            cur.execute("CREATE INDEX ON hood_tax_totals (tax_year);")
            cur.execute("CREATE INDEX ON hood_tax_totals (hood_code);")
