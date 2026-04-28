from __future__ import annotations

import datetime as dt
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit.models import SedroWoolleyPermit
from openskagit.services.sedro_woolley_permits import SedroWoolleyPermitCrawler, normalize_text


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Verify permit status accuracy by comparing database permits against live Sedro-Woolley portal data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=10,
            help="Rolling window size in days to verify (default: 10).",
        )
        parser.add_argument(
            "--end-date",
            default=dt.date.today().isoformat(),
            help="Verification window end date (YYYY-MM-DD, default: today).",
        )
        parser.add_argument(
            "--delay-ms",
            type=int,
            default=150,
            help="Delay between HTTP requests in milliseconds.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            help="Optional page limit for the live search window.",
        )
        parser.add_argument(
            "--failure-samples",
            type=int,
            default=200,
            help="Max live-fetch failure examples collected in output.",
        )
        parser.add_argument(
            "--sample-limit",
            type=int,
            default=25,
            help="Max sample rows printed per mismatch category.",
        )
        parser.add_argument(
            "--fail-on-diff",
            action="store_true",
            help="Exit non-zero when mismatches, missing records, or fetch failures are found.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be at least 1")
        if options["delay_ms"] < 0:
            raise CommandError("--delay-ms must be at least 0")
        if options["timeout"] < 1:
            raise CommandError("--timeout must be at least 1")
        if options["max_pages"] is not None and options["max_pages"] < 1:
            raise CommandError("--max-pages must be at least 1 when provided")
        if options["failure_samples"] < 1:
            raise CommandError("--failure-samples must be at least 1")
        if options["sample_limit"] < 1:
            raise CommandError("--sample-limit must be at least 1")

        try:
            end_date = dt.date.fromisoformat(options["end_date"])
        except ValueError as exc:
            raise CommandError(f"Invalid --end-date: {exc}") from exc

        start_date = end_date - dt.timedelta(days=days - 1)
        crawler = SedroWoolleyPermitCrawler(
            delay_ms=options["delay_ms"],
            timeout_seconds=options["timeout"],
        )

        live_result, live_records = crawler.fetch_range_records(
            start_date,
            end_date,
            max_pages=options["max_pages"],
            failure_sample_limit=options["failure_samples"],
        )

        live_by_external_id = {record["external_id"]: record for record in live_records}
        live_external_ids = set(live_by_external_id.keys())

        db_live_rows = {
            row["external_id"]: row
            for row in SedroWoolleyPermit.objects.filter(external_id__in=live_external_ids).values(
                "external_id",
                "permit_number",
                "status",
                "detail_url",
                "permit_date",
            )
        }
        db_window_rows = {
            row["external_id"]: row
            for row in SedroWoolleyPermit.objects.filter(
                permit_date__gte=start_date,
                permit_date__lte=end_date,
            ).values(
                "external_id",
                "permit_number",
                "status",
                "detail_url",
                "permit_date",
            )
        }
        db_window_external_ids = set(db_window_rows.keys())

        status_matches = 0
        status_mismatches: list[dict[str, str]] = []
        missing_in_db: list[dict[str, str]] = []

        for external_id in sorted(live_external_ids):
            live = live_by_external_id[external_id]
            live_status = normalize_text(str(live.get("status") or ""))
            permit_number = normalize_text(str(live.get("permit_number") or external_id))
            db_row = db_live_rows.get(external_id)
            if db_row is None:
                missing_in_db.append(
                    {
                        "external_id": external_id,
                        "permit_number": permit_number,
                        "live_status": live_status,
                        "detail_url": str(live.get("detail_url") or ""),
                    }
                )
                continue

            db_status = normalize_text(str(db_row.get("status") or ""))
            if db_status == live_status:
                status_matches += 1
                continue
            status_mismatches.append(
                {
                    "external_id": external_id,
                    "permit_number": permit_number or normalize_text(str(db_row.get("permit_number") or external_id)),
                    "db_status": db_status,
                    "live_status": live_status,
                    "detail_url": str(live.get("detail_url") or db_row.get("detail_url") or ""),
                }
            )

        missing_in_live_ids = sorted(db_window_external_ids - live_external_ids)
        missing_in_live = [
            {
                "external_id": external_id,
                "permit_number": normalize_text(str(db_window_rows[external_id].get("permit_number") or external_id)),
                "db_status": normalize_text(str(db_window_rows[external_id].get("status") or "")),
                "detail_url": str(db_window_rows[external_id].get("detail_url") or ""),
            }
            for external_id in missing_in_live_ids
        ]

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley permit verification completed."))
        self.stdout.write(f"range: {start_date.isoformat()}..{end_date.isoformat()}")
        self.stdout.write(f"list_pages_fetched: {live_result.list_pages_fetched}")
        self.stdout.write(f"detail_pages_fetched: {live_result.detail_pages_fetched}")
        self.stdout.write(f"live_permits_seen: {live_result.permits_seen}")
        self.stdout.write(f"db_permits_in_window: {len(db_window_external_ids)}")
        self.stdout.write(f"status_matches: {status_matches}")
        self.stdout.write(f"status_mismatches: {len(status_mismatches)}")
        self.stdout.write(f"missing_in_db: {len(missing_in_db)}")
        self.stdout.write(f"missing_in_live: {len(missing_in_live)}")
        self.stdout.write(f"live_fetch_failures: {live_result.permit_failures}")

        sample_limit = int(options["sample_limit"])

        if status_mismatches:
            self.stdout.write("status_mismatch_samples:")
            for row in status_mismatches[:sample_limit]:
                self.stdout.write(
                    "  "
                    f"external_id={row['external_id']} "
                    f"permit_number={row['permit_number']} "
                    f"db_status='{row['db_status']}' "
                    f"live_status='{row['live_status']}' "
                    f"detail_url={row['detail_url']}"
                )

        if missing_in_db:
            self.stdout.write("missing_in_db_samples:")
            for row in missing_in_db[:sample_limit]:
                self.stdout.write(
                    "  "
                    f"external_id={row['external_id']} "
                    f"permit_number={row['permit_number']} "
                    f"live_status='{row['live_status']}' "
                    f"detail_url={row['detail_url']}"
                )

        if missing_in_live:
            self.stdout.write("missing_in_live_samples:")
            for row in missing_in_live[:sample_limit]:
                self.stdout.write(
                    "  "
                    f"external_id={row['external_id']} "
                    f"permit_number={row['permit_number']} "
                    f"db_status='{row['db_status']}' "
                    f"detail_url={row['detail_url']}"
                )

        if live_result.failures:
            self.stdout.write("live_fetch_failure_samples:")
            for row in (live_result.failures or [])[:sample_limit]:
                self.stdout.write(
                    "  "
                    f"external_id={row.get('external_id', '')} "
                    f"url={row.get('url', '')} "
                    f"error={row.get('error', '')}"
                )

        has_diffs = bool(status_mismatches or missing_in_db or missing_in_live or live_result.permit_failures)
        if options["fail_on_diff"] and has_diffs:
            raise CommandError("Permit verification found status differences or missing records.")
