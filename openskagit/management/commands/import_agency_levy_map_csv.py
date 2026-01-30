from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, Optional

from django.core.management.base import BaseCommand, CommandError

from openskagit.models import AgencyLevyMap


class Command(BaseCommand):
    help = "Import agency_levy_map rows from a CSV export."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            required=True,
            help="Path to CSV file (e.g., data/agency_levy_map_ai.csv)",
        )
        parser.add_argument(
            "--min-confidence",
            type=float,
            default=0.85,
            help="Minimum confidence required to import (default: 0.85)",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing agency_levy_map rows before importing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print summary without writing to the database.",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        min_confidence = options["min_confidence"]
        truncate = options["truncate"]
        dry_run = options["dry_run"]

        if not input_path.exists():
            raise CommandError(f"File not found: {input_path}")

        rows = list(self._load_rows(input_path))
        if not rows:
            raise CommandError("No rows found in CSV.")

        eligible = [
            row for row in rows
            if row["mcag"] and row["confidence"] is not None and row["confidence"] >= min_confidence
        ]

        self.stdout.write(f"Rows in CSV: {len(rows)}")
        self.stdout.write(f"Eligible rows (mcag + confidence >= {min_confidence}): {len(eligible)}")

        if dry_run:
            self.stdout.write("Dry run: no database changes made.")
            return

        if truncate:
            self.stdout.write("Deleting existing agency_levy_map rows…")
            AgencyLevyMap.objects.all().delete()

        applied = 0
        for row in eligible:
            obj, _ = AgencyLevyMap.objects.update_or_create(
                tdcode=row["tdcode"],
                mcag=row["mcag"],
                defaults={
                    "agency_name": row["agency_name"],
                    "agency_type": row.get("district_type_hint") or "",
                    "notes": row.get("notes") or "",
                    "is_primary": True,
                },
            )
            applied += 1

        self.stdout.write(self.style.SUCCESS(f"✓ Imported {applied} rows into agency_levy_map"))

    def _load_rows(self, path: Path) -> Iterable[Dict[str, Optional[str]]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                tdcode = (row.get("tdcode") or "").strip()
                mcag = (row.get("mcag") or "").strip()
                if not tdcode:
                    continue
                confidence = self._parse_float(row.get("confidence"))
                yield {
                    "tdcode": tdcode,
                    "district_name": (row.get("district_name") or "").strip(),
                    "district_type_hint": (row.get("district_type_hint") or "").strip(),
                    "mcag": mcag,
                    "agency_name": (row.get("agency_name") or "").strip(),
                    "confidence": confidence,
                    "notes": self._build_notes(row),
                }

    def _parse_float(self, value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).strip())
        except ValueError:
            return None

    def _build_notes(self, row: Dict[str, Optional[str]]) -> str:
        match_type = (row.get("match_type") or "").strip()
        reason = (row.get("reason") or "").strip()
        confidence = (row.get("confidence") or "").strip()
        parts = []
        if match_type:
            parts.append(f"ai_match={match_type}")
        if confidence:
            parts.append(f"confidence={confidence}")
        if reason:
            parts.append(f"reason={reason}")
        return "; ".join(parts)
