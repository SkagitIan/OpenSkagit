from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from django.core.management.base import BaseCommand

from openskagit.models import ParcelHistory

TOTAL_TAX_KEYS = (
    "Property Tax, Assessments, and Fees Total",
    "Total Due",
)

VALUE_KEYS = (
    "Total Market Value",
    "Taxable Value",
)

LAND_VALUE_KEYS = (
    "Land Market Value",
    "Land Assessed Value",
)

BUILDING_VALUE_KEYS = (
    "Building Market Value",
    "Building Assessed Value",
)


def _coerce_dict(payload: Any) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    if not isinstance(payload, dict):
        return None
    return payload


def _coerce_rows(rows: Any) -> List[Dict[str, Any]]:
    if not rows:
        return []
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except Exception:
            return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]

def _summary_from_rows(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    summary = {}
    for row in rows:
        if row.get("Source") != "TaxesTab":
            continue
        field = row.get("Summary Field")
        value = row.get("Summary Value")
        if field:
            summary[str(field)] = value
    return summary or None


def _extract_year_from_summary(summary: Dict[str, Any]) -> Optional[int]:
    years = []
    for key in summary.keys():
        match = re.search(r"(20\d{2})", str(key))
        if match:
            try:
                years.append(int(match.group(1)))
            except ValueError:
                continue
    return max(years) if years else None


def _find_summary_value(summary: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
    for key in keys:
        if key in summary:
            value = summary.get(key)
            if value:
                return str(value)
    return None


def _find_year_specific_value(summary: Dict[str, Any], year: int, suffixes: Tuple[str, ...]) -> Optional[str]:
    for suffix in suffixes:
        key = f"{year} {suffix}"
        if key in summary:
            value = summary.get(key)
            if value:
                return str(value)
    return None


def _pick_total_tax(summary: Dict[str, Any], year: int) -> Optional[str]:
    year_value = _find_year_specific_value(summary, year, TOTAL_TAX_KEYS)
    if year_value:
        return year_value
    return _find_summary_value(summary, TOTAL_TAX_KEYS)


def _insert_row(
    rows: List[Dict[str, Any]],
    row: Dict[str, Any],
    tax_year: int,
    replace: bool,
) -> Tuple[List[Dict[str, Any]], bool]:
    tax_year_str = str(tax_year)
    existing_index = None
    for idx, existing in enumerate(rows):
        if existing.get("TAX YEAR") == tax_year_str:
            existing_index = idx
            break
    if existing_index is not None:
        if not replace:
            return rows, False
        rows[existing_index] = row
        return rows, True

    insert_index = None
    for idx, existing in enumerate(rows):
        if "TAX YEAR" not in existing:
            insert_index = idx
            break
    if insert_index is None:
        rows.append(row)
    else:
        rows.insert(insert_index, row)
    return rows, True


class Command(BaseCommand):
    help = "Backfill ParcelHistory.rows with a tax-year row derived from ParcelHistory.taxes."

    def add_arguments(self, parser):
        parser.add_argument("--tax-year", type=int, default=None, help="Override tax year for the inserted row.")
        parser.add_argument("--value-year", type=int, default=None, help="Override value year for the inserted row.")
        parser.add_argument(
            "--value-year-offset",
            type=int,
            default=-1,
            help="Offset from tax year to compute value year when --value-year is not provided.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Limit number of ParcelHistory rows processed.")
        parser.add_argument("--replace", action="store_true", help="Replace existing row for the tax year.")
        parser.add_argument("--dry-run", action="store_true", help="Compute changes but do not write to the DB.")

    def handle(self, *args, **options):
        limit = options["limit"]
        replace = options["replace"]
        dry_run = options["dry_run"]
        override_tax_year = options["tax_year"]
        override_value_year = options["value_year"]
        value_year_offset = options["value_year_offset"]

        qs = ParcelHistory.objects.only("id", "parcel_number", "rows", "taxes")
        if limit:
            qs = qs[:limit]

        updated = 0
        skipped = 0
        for record in qs.iterator():
            taxes_payload = _coerce_dict(record.taxes)
            summary = None
            if taxes_payload:
                summary = taxes_payload.get("summary") or {}
                if isinstance(summary, str):
                    try:
                        summary = json.loads(summary)
                    except Exception:
                        summary = {}
                if not isinstance(summary, dict):
                    summary = None
            if not summary:
                rows = _coerce_rows(record.rows)
                summary = _summary_from_rows(rows)
            if not summary:
                skipped += 1
                continue

            tax_year = override_tax_year or _extract_year_from_summary(summary)
            if not tax_year:
                skipped += 1
                continue
            value_year = override_value_year if override_value_year is not None else tax_year + value_year_offset

            tax_total = _pick_total_tax(summary, tax_year)
            market_total = _find_summary_value(summary, VALUE_KEYS)
            taxable_value = _find_summary_value(summary, ("Taxable Value",))
            land_value = _find_summary_value(summary, LAND_VALUE_KEYS)
            building_value = _find_summary_value(summary, BUILDING_VALUE_KEYS)

            if not tax_total or not (market_total or taxable_value):
                skipped += 1
                continue

            row = {
                "TAX YEAR": str(tax_year),
                "VALUE YEAR": str(value_year),
                "TAX": tax_total,
            }
            if building_value:
                row["BUILDING"] = building_value
            if land_value:
                row["LAND MARKET"] = land_value
            if market_total:
                row["MARKET TOTAL"] = market_total
            if taxable_value:
                row["TAXABLE VALUE"] = taxable_value
                row["ASSESSED TOTAL"] = taxable_value

            rows = _coerce_rows(record.rows)
            next_rows, changed = _insert_row(rows, row, tax_year, replace)
            if not changed:
                skipped += 1
                continue

            updated += 1
            if dry_run:
                continue

            record.rows = next_rows
            record.save(update_fields=["rows"])

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no changes written."))
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} ParcelHistory records."))
        self.stdout.write(f"Skipped {skipped} records.")
