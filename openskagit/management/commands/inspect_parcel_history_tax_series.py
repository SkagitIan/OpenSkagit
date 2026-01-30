from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

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


def _extract_first_money(row: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[Decimal]:
    for key in keys:
        value = _parse_money(row.get(key))
        if value is not None:
            return value
    return None


class Command(BaseCommand):
    help = "Inspect ParcelHistory.rows value/tax parsing for a single parcel."

    def add_arguments(self, parser):
        parser.add_argument("parcel_number", type=str, help="Parcel number to inspect.")
        parser.add_argument("--year", type=int, default=None, help="Filter to a single year.")

    def handle(self, *args, **options):
        parcel_number = options["parcel_number"].strip()
        target_year = options["year"]

        history = (
            ParcelHistory.objects.filter(parcel_number=parcel_number)
            .only("parcel_number", "rows", "taxes", "neighborhood_code")
            .first()
        )
        if not history:
            self.stdout.write(self.style.ERROR("ParcelHistory record not found."))
            return

        master = (
            MasterParcel.objects.filter(parcel_number=parcel_number)
            .only("hood_code", "hood_description", "total_market_value")
            .first()
        )

        hood_code = master.hood_code if master else None
        hood_desc = master.hood_description if master else None
        fallback_value = master.total_market_value if master else None

        self.stdout.write(
            self.style.SUCCESS(
                f"Parcel {parcel_number} | hood={hood_code or '—'} {hood_desc or ''}".strip()
            )
        )

        rows = history.rows
        if not isinstance(rows, list):
            self.stdout.write(self.style.ERROR("ParcelHistory.rows is not a list."))
            return

        parsed = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            year = _extract_year(row)
            if year is None:
                continue
            if target_year and year != target_year:
                continue
            value = _extract_first_money(row, VALUE_KEYS)
            tax = _extract_first_money(row, TAX_KEYS)
            value_source = "rows"
            if value is None and fallback_value:
                value = _parse_money(fallback_value)
                value_source = "masterparcel.total_market_value"
            parsed.append((year, value, tax, value_source))

        if not parsed:
            self.stdout.write(self.style.WARNING("No rows matched the filters."))
            return

        parsed.sort(key=lambda item: item[0])
        for year, value, tax, value_source in parsed:
            self.stdout.write(
                f"{year}: value={value or '—'} ({value_source}) | tax={tax or '—'}"
            )
