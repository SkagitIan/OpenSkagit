import calendar
import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from openskagit.models import Sales

load_dotenv()


def _subtract_months(base_date: date, months: int) -> date:
    year = base_date.year
    month = base_date.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_")


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _parse_int(value: str | None) -> int | None:
    raw = _normalize_text(value)
    if not raw:
        return None
    raw = raw.replace(",", "")
    try:
        return int(raw)
    except ValueError:
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None


def _parse_float(value: str | None) -> float | None:
    raw = _normalize_text(value)
    if not raw:
        return None
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_datetime(value: str | None, current_year: int) -> tuple[datetime | None, bool]:
    raw = _normalize_text(value)
    if not raw:
        return None, False

    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None, False

    corrected_year = False
    if parsed.year > current_year + 1:
        year_text = str(parsed.year)
        if len(year_text) == 4 and year_text[::-1].isdigit():
            reversed_year = int(year_text[::-1])
            if 1900 <= reversed_year <= current_year + 1:
                parsed = parsed.replace(year=reversed_year)
                corrected_year = True

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed, corrected_year


def _fingerprint(
    sale_id: int | None,
    parcel_number: str,
    sale_date: datetime | None,
    sale_price: int | None,
    recording_number: str | None,
) -> tuple[int | None, str, date | None, int | None, str]:
    return (
        sale_id,
        _normalize_text(parcel_number),
        sale_date.date() if sale_date else None,
        sale_price,
        _normalize_text(recording_number),
    )


def _activity_date(sale_date: datetime | None, deed_date: datetime | None) -> date | None:
    sale_day = sale_date.date() if sale_date else None
    deed_day = deed_date.date() if deed_date else None
    if sale_day and deed_day:
        return max(sale_day, deed_day)
    return sale_day or deed_day


class Command(BaseCommand):
    help = (
        "Import incremental Sales.txt rows into the sales table, "
        "adding only rows that do not already exist."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--path",
            default="data/Sales.txt",
            help="Path to pipe-delimited Sales.txt file (default: data/Sales.txt).",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=6,
            help="Lookback window in months (default: 6).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Bulk insert batch size (default: 1000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report only; do not insert rows.",
        )

    def handle(self, *args, **options) -> None:
        path = Path(options["path"]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        months = options["months"]
        if months < 0:
            raise CommandError("--months must be >= 0")

        batch_size = options["batch_size"]
        if batch_size <= 0:
            raise CommandError("--batch-size must be > 0")

        today = timezone.localdate()
        cutoff_date = _subtract_months(today, months)
        current_year = today.year

        self.stdout.write(
            f"Reading {path} and importing rows with activity_date between {cutoff_date} and {today}."
        )

        stats: dict[str, int] = {
            "rows_read": 0,
            "rows_missing_sale_date": 0,
            "rows_bad_sale_date": 0,
            "rows_bad_deed_date": 0,
            "rows_missing_activity_date": 0,
            "rows_before_cutoff": 0,
            "rows_after_today": 0,
            "year_corrections": 0,
            "candidate_rows": 0,
            "skipped_existing_fingerprint": 0,
            "skipped_duplicate_in_file": 0,
            "to_create": 0,
        }

        candidates: list[tuple[tuple[int | None, str, date | None, int | None, str], dict[str, Any]]] = []

        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle, delimiter="|")

            if not reader.fieldnames:
                raise CommandError("Input file has no header row.")

            for raw_row in reader:
                stats["rows_read"] += 1
                row = {_normalize_header(k): v for k, v in raw_row.items() if k is not None}

                sale_date_raw = row.get("sale_date")
                sale_date: datetime | None = None
                if not _normalize_text(sale_date_raw):
                    stats["rows_missing_sale_date"] += 1
                else:
                    sale_date, corrected_year = _parse_datetime(sale_date_raw, current_year)
                    if corrected_year:
                        stats["year_corrections"] += 1
                    if sale_date is None:
                        stats["rows_bad_sale_date"] += 1

                deed_date, deed_date_corrected_year = _parse_datetime(row.get("deed_date"), current_year)
                if deed_date_corrected_year:
                    stats["year_corrections"] += 1
                if _normalize_text(row.get("deed_date")) and deed_date is None:
                    stats["rows_bad_deed_date"] += 1

                activity_day = _activity_date(sale_date=sale_date, deed_date=deed_date)
                if activity_day is None:
                    stats["rows_missing_activity_date"] += 1
                    continue
                if activity_day < cutoff_date:
                    stats["rows_before_cutoff"] += 1
                    continue
                if activity_day > today:
                    stats["rows_after_today"] += 1
                    continue

                sale_id = _parse_int(row.get("saleid") or row.get("sale_id"))
                sale_price = _parse_int(row.get("sale_price"))

                parcel_number = _normalize_text(row.get("parcel_number"))
                recording_number = _normalize_text(row.get("recording_number"))

                values = {
                    "sale_id": sale_id,
                    "parcel_number": parcel_number,
                    "account_number": _normalize_text(row.get("account_number")) or None,
                    "seller_name": _normalize_text(row.get("seller_name")) or None,
                    "buyer_name": _normalize_text(row.get("buyer_name")) or None,
                    "sale_price": sale_price,
                    "sale_date": sale_date,
                    "sale_type": _normalize_text(row.get("sale_type")) or None,
                    "recording_number": recording_number or None,
                    "deed_type": _normalize_text(row.get("deed_type")) or None,
                    "deed_date": deed_date,
                    "revaluation_area": _parse_float(row.get("reval_area") or row.get("revaluation_area")),
                    "excise_number": _parse_float(row.get("excise_number")),
                }

                row_fingerprint = _fingerprint(
                    sale_id=values["sale_id"],
                    parcel_number=values["parcel_number"],
                    sale_date=values["sale_date"],
                    sale_price=values["sale_price"],
                    recording_number=values["recording_number"],
                )

                candidates.append((row_fingerprint, values))
                stats["candidate_rows"] += 1

        if not candidates:
            self.stdout.write(self.style.WARNING("No candidate rows found in the requested date window."))
            return

        existing_fingerprints = {
            _fingerprint(
                sale_id=s.sale_id,
                parcel_number=s.parcel_number,
                sale_date=s.sale_date,
                sale_price=s.sale_price,
                recording_number=s.recording_number,
            )
            for s in Sales.objects.filter(
                Q(sale_date__date__gte=cutoff_date, sale_date__date__lte=today)
                | Q(deed_date__date__gte=cutoff_date, deed_date__date__lte=today)
            ).only("sale_id", "parcel_number", "sale_date", "sale_price", "recording_number")
        }

        seen_new_fingerprints: set[tuple[int | None, str, date | None, int | None, str]] = set()
        to_create: list[Sales] = []

        for row_fingerprint, values in candidates:
            if row_fingerprint in existing_fingerprints:
                stats["skipped_existing_fingerprint"] += 1
                continue
            if row_fingerprint in seen_new_fingerprints:
                stats["skipped_duplicate_in_file"] += 1
                continue

            to_create.append(Sales(**values))
            seen_new_fingerprints.add(row_fingerprint)

        stats["to_create"] = len(to_create)

        self.stdout.write(f"Rows read: {stats['rows_read']:,}")
        self.stdout.write(f"Missing sale_date: {stats['rows_missing_sale_date']:,}")
        self.stdout.write(f"Bad sale_date: {stats['rows_bad_sale_date']:,}")
        self.stdout.write(f"Bad deed_date: {stats['rows_bad_deed_date']:,}")
        self.stdout.write(f"Missing activity date: {stats['rows_missing_activity_date']:,}")
        self.stdout.write(f"Before cutoff: {stats['rows_before_cutoff']:,}")
        self.stdout.write(f"After today: {stats['rows_after_today']:,}")
        self.stdout.write(f"Year corrections applied: {stats['year_corrections']:,}")
        self.stdout.write(f"Candidates in window: {stats['candidate_rows']:,}")
        self.stdout.write(f"Skipped existing (fingerprint): {stats['skipped_existing_fingerprint']:,}")
        self.stdout.write(f"Skipped duplicates in file: {stats['skipped_duplicate_in_file']:,}")
        self.stdout.write(self.style.SUCCESS(f"Rows to insert: {stats['to_create']:,}"))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run enabled. No rows inserted."))
            return

        if not to_create:
            self.stdout.write(self.style.SUCCESS("No new rows to insert."))
            return

        with transaction.atomic():
            Sales.objects.bulk_create(to_create, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS(f"Inserted {len(to_create):,} new sales rows."))
