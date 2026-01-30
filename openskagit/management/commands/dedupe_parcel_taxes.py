import json
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import ParcelHistory


class Command(BaseCommand):
    help = "Deduplicate taxes.line_items payloads in ParcelHistory records"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Limit number of parcels to scan")
        parser.add_argument("--dry-run", action="store_true", help="Report only; do not write changes")

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]

        qs = ParcelHistory.objects.exclude(taxes={}).only("id", "parcel_number", "taxes")
        if limit:
            qs = qs[:limit]

        total = 0
        changed = 0
        for record in qs.iterator():
            total += 1
            taxes = record.taxes
            if isinstance(taxes, str):
                try:
                    taxes = json.loads(taxes)
                except Exception:
                    continue
            if not isinstance(taxes, dict):
                continue

            line_items = taxes.get("line_items")
            if not line_items:
                continue
            if isinstance(line_items, str):
                try:
                    line_items = json.loads(line_items)
                except Exception:
                    continue
            if not isinstance(line_items, list):
                continue

            deduped = self._dedupe(line_items)
            if deduped == line_items:
                continue

            changed += 1
            if not dry_run:
                taxes["line_items"] = deduped
                record.taxes = taxes
                record.save(update_fields=["taxes"])

        self.stdout.write(self.style.SUCCESS(
            f"Scanned {total} parcels; deduped {changed} payloads"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no changes written."))

    def _dedupe(self, items: List[Dict]) -> List[Dict]:
        seen = {}
        for item in items:
            key = (
                str(item.get("tax_district") or item.get("Tax District") or "").strip(),
                str(item.get("rate") or item.get("Rate") or "").strip(),
                str(item.get("amount") or item.get("Amount") or "").strip(),
            )
            if not key[0]:
                continue
            if key in seen:
                # Prefer the first occurrence, ignore duplicates
                continue
            seen[key] = {
                "tax_district": key[0],
                "rate": key[1],
                "amount": key[2],
            }
        return list(seen.values())
