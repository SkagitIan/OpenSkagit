from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

from django.core.management.base import BaseCommand

from openskagit.models import MasterParcel, ParcelHistory


VALUE_KEYS = (
    "MARKET TOTAL",
    "ASSESSED TOTAL",
    "TAXABLE VALUE",
)

TAX_KEYS = (
    "TAX",
    "PROPERTY TAX",
    "TOTAL TAX",
)


def _parse_money(raw: Any) -> Optional[Decimal]:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        return Decimal(text)
    except Exception:
        return None


def _extract_year(row: Dict[str, Any]) -> Optional[int]:
    year_raw = row.get("VALUE YEAR") or row.get("TAX YEAR")
    if not year_raw:
        return None
    try:
        return int(str(year_raw).strip())
    except (TypeError, ValueError):
        return None


def _extract_first_money(row: Dict[str, Any], keys: Iterable[str]) -> Optional[Decimal]:
    for key in keys:
        value = _parse_money(row.get(key))
        if value is not None:
            return value
    return None


def _extract_statement_year(summary: Dict[str, Any]) -> Optional[int]:
    for key in summary.keys():
        text = str(key)
        for token in text.split():
            if token.isdigit() and len(token) == 4 and token.startswith("20"):
                try:
                    return int(token)
                except ValueError:
                    continue
    return None


class Command(BaseCommand):
    help = "Read-only audit of ParcelHistory rows for tax/value fairness readiness."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Limit parcels to scan.")
        parser.add_argument("--year", type=int, default=None, help="Filter to a single tax/value year.")
        parser.add_argument("--sample", type=int, default=0, help="Print sample parcel summaries.")

    def handle(self, *args, **options):
        limit = options["limit"]
        target_year = options["year"]
        sample_size = max(0, int(options["sample"] or 0))

        qs = ParcelHistory.objects.exclude(rows__isnull=True).only(
            "parcel_number",
            "rows",
            "taxes",
        )
        if limit:
            qs = qs[:limit]

        totals = Counter()
        year_counts = Counter()
        missing_value_keys = Counter()
        missing_tax_keys = Counter()
        hood_counts = Counter()
        statement_year_counts = Counter()
        line_item_counts = Counter()
        sample_rows = []

        batch = []
        batch_size = 1000

        for record in qs.iterator():
            batch.append(record)
            if len(batch) >= batch_size:
                self._process_batch(
                    batch,
                    target_year,
                    totals,
                    year_counts,
                    missing_value_keys,
                    missing_tax_keys,
                    hood_counts,
                    statement_year_counts,
                    line_item_counts,
                    sample_rows,
                    sample_size,
                )
                batch = []

        if batch:
            self._process_batch(
                batch,
                target_year,
                totals,
                year_counts,
                missing_value_keys,
                missing_tax_keys,
                hood_counts,
                statement_year_counts,
                line_item_counts,
                sample_rows,
                sample_size,
            )

        self.stdout.write(self.style.SUCCESS("ParcelHistory tax/value audit (read-only)"))
        self.stdout.write(f"Parcels scanned: {totals['parcels_scanned']}")
        self.stdout.write(f"Rows scanned: {totals['rows_scanned']}")
        self.stdout.write(f"Rows with year: {totals['rows_with_year']}")
        self.stdout.write(f"Rows with value: {totals['rows_with_value']}")
        self.stdout.write(f"Rows with tax: {totals['rows_with_tax']}")
        self.stdout.write(f"Rows with value+tax: {totals['rows_with_value_tax']}")
        self.stdout.write(f"Rows with value fallback: {totals['rows_with_value_fallback']}")
        self.stdout.write(f"Parcels with taxes payload: {totals['parcels_with_taxes']}")
        self.stdout.write(f"Parcels with tax statement year: {totals['parcels_with_statement_year']}")
        self.stdout.write(f"Parcels with line items: {totals['parcels_with_line_items']}")
        if target_year:
            self.stdout.write(f"Filtered year: {target_year}")

        if year_counts:
            self.stdout.write("\nTop years by row count:")
            for year, count in year_counts.most_common(10):
                self.stdout.write(f"  {year}: {count}")

        if hood_counts:
            self.stdout.write("\nTop neighborhoods by parcel rows:")
            for hood, count in hood_counts.most_common(10):
                self.stdout.write(f"  {hood}: {count}")

        if statement_year_counts:
            self.stdout.write("\nTop tax statement years:")
            for year, count in statement_year_counts.most_common(10):
                self.stdout.write(f"  {year}: {count}")

        if line_item_counts:
            self.stdout.write("\nLine item counts (per parcel payload):")
            for count, total in line_item_counts.most_common(10):
                self.stdout.write(f"  {count} items: {total}")

        if missing_value_keys:
            self.stdout.write("\nMost common missing value key situations:")
            for label, count in missing_value_keys.most_common(8):
                self.stdout.write(f"  {label}: {count}")

        if missing_tax_keys:
            self.stdout.write("\nMost common missing tax key situations:")
            for label, count in missing_tax_keys.most_common(8):
                self.stdout.write(f"  {label}: {count}")

        if sample_rows:
            self.stdout.write("\nSample parcel summaries:")
            for summary in sample_rows:
                self.stdout.write(summary)

    def _process_batch(
        self,
        batch,
        target_year,
        totals,
        year_counts,
        missing_value_keys,
        missing_tax_keys,
        hood_counts,
        statement_year_counts,
        line_item_counts,
        sample_rows,
        sample_size,
    ):
        parcel_numbers = [record.parcel_number for record in batch]
        hood_map = {
            row.parcel_number: (
                row.hood_code or "",
                row.hood_description or "",
                row.total_market_value,
            )
            for row in MasterParcel.objects.filter(parcel_number__in=parcel_numbers).only(
                "parcel_number",
                "hood_code",
                "hood_description",
                "total_market_value",
            )
        }

        totals["parcels_scanned"] += len(batch)

        for record in batch:
            hood_code, hood_desc, fallback_value = hood_map.get(record.parcel_number, ("", "", None))

            taxes_payload = record.taxes
            if taxes_payload:
                totals["parcels_with_taxes"] += 1
                if isinstance(taxes_payload, str):
                    try:
                        taxes_payload = json.loads(taxes_payload)
                    except Exception:
                        taxes_payload = {}
                if isinstance(taxes_payload, dict):
                    summary = taxes_payload.get("summary") or {}
                    if isinstance(summary, str):
                        try:
                            summary = json.loads(summary)
                        except Exception:
                            summary = {}
                    line_items = taxes_payload.get("line_items") or []
                    if isinstance(summary, dict):
                        statement_year = _extract_statement_year(summary)
                        if statement_year:
                            totals["parcels_with_statement_year"] += 1
                            statement_year_counts[statement_year] += 1
                    if isinstance(line_items, list):
                        totals["parcels_with_line_items"] += 1
                        line_item_counts[len(line_items)] += 1

            history = record.rows
            if not isinstance(history, list):
                continue
            for row in history:
                if not isinstance(row, dict):
                    continue
                totals["rows_scanned"] += 1
                year = _extract_year(row)
                if year is None:
                    continue
                if target_year and year != target_year:
                    continue
                totals["rows_with_year"] += 1
                year_counts[year] += 1

                value = _extract_first_money(row, VALUE_KEYS)
                if value is None:
                    missing_value_keys["missing_value_keys"] += 1
                else:
                    totals["rows_with_value"] += 1

                tax = _extract_first_money(row, TAX_KEYS)
                if tax is None:
                    missing_tax_keys["missing_tax_keys"] += 1
                else:
                    totals["rows_with_tax"] += 1

                if value is not None and tax is not None:
                    totals["rows_with_value_tax"] += 1

                if value is None:
                    if fallback_value:
                        totals["rows_with_value_fallback"] += 1

                if hood_code:
                    hood_counts[f"{hood_code} {hood_desc}".strip()] += 1

                if sample_size and len(sample_rows) < sample_size:
                    sample_rows.append(
                        f"  {record.parcel_number} | {year} | hood={hood_code or '—'} "
                        f"| value={value or '—'} | tax={tax or '—'}"
                    )
