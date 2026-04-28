from __future__ import annotations

import datetime as dt
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import SedroWoolleyPermitSyncRun
from openskagit.services.sedro_woolley_permits import SedroWoolleyPermitCrawler, split_date_windows


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Backfill Sedro-Woolley permits over a date range, chunked by month windows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            default="2019-01-01",
            help="Backfill start date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--end-date",
            default=dt.date.today().isoformat(),
            help="Backfill end date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--chunk-months",
            type=int,
            default=12,
            help="Month span per chunk (default: 12).",
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
            help="Optional page limit per chunk.",
        )
        parser.add_argument(
            "--failure-samples",
            type=int,
            default=200,
            help="Max failure examples stored on the run record.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and parse permits without writing permit rows.",
        )
        parser.add_argument(
            "--stop-on-error",
            action="store_true",
            help="Stop immediately when one chunk fails.",
        )

    def handle(self, *args, **options):
        try:
            start_date = dt.date.fromisoformat(options["start_date"])
            end_date = dt.date.fromisoformat(options["end_date"])
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}") from exc

        chunk_months = options["chunk_months"]
        if chunk_months < 1:
            raise CommandError("--chunk-months must be at least 1")
        if start_date > end_date:
            raise CommandError("--start-date cannot be after --end-date")
        if options["delay_ms"] < 0:
            raise CommandError("--delay-ms must be at least 0")
        if options["timeout"] < 1:
            raise CommandError("--timeout must be at least 1")
        if options["max_pages"] is not None and options["max_pages"] < 1:
            raise CommandError("--max-pages must be at least 1 when provided")
        if options["failure_samples"] < 1:
            raise CommandError("--failure-samples must be at least 1")

        windows = split_date_windows(start_date, end_date, chunk_months)
        run_id = f"swperm-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

        run = SedroWoolleyPermitSyncRun.objects.create(
            run_id=run_id,
            mode=SedroWoolleyPermitSyncRun.MODE_BACKFILL,
            start_date=start_date,
            end_date=end_date,
            chunk_months=chunk_months,
            dry_run=bool(options["dry_run"]),
            started_at=timezone.now(),
        )

        crawler = SedroWoolleyPermitCrawler(
            delay_ms=options["delay_ms"],
            timeout_seconds=options["timeout"],
        )

        started = time.perf_counter()
        failures: list[dict[str, str]] = []

        self.stdout.write(
            f"run_id: {run_id} | windows: {len(windows)} | range: {start_date.isoformat()}..{end_date.isoformat()}"
        )

        for idx, (window_start, window_end) in enumerate(windows, start=1):
            try:
                result = crawler.crawl_range(
                    window_start,
                    window_end,
                    persist=not options["dry_run"],
                    max_pages=options["max_pages"],
                    failure_sample_limit=options["failure_samples"],
                )
            except Exception as exc:
                run.permit_failures += 1
                if len(failures) < options["failure_samples"]:
                    failures.append(
                        {
                            "window_start": window_start.isoformat(),
                            "window_end": window_end.isoformat(),
                            "error": str(exc),
                        }
                    )
                run.failures = failures
                run.save(update_fields=["permit_failures", "failures", "updated_at"])
                self.stdout.write(
                    self.style.WARNING(
                        f"[{idx}/{len(windows)}] {window_start}..{window_end} FAILED: {exc}"
                    )
                )
                if options["stop_on_error"]:
                    break
                continue

            run.list_pages_fetched += result.list_pages_fetched
            run.detail_pages_fetched += result.detail_pages_fetched
            run.permits_seen += result.permits_seen
            run.permits_new += result.permits_new
            run.permits_updated += result.permits_updated
            run.permits_unchanged += result.permits_unchanged
            run.permit_failures += result.permit_failures

            for row in result.failures or []:
                if len(failures) >= options["failure_samples"]:
                    break
                payload = {
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "external_id": row.get("external_id", ""),
                    "url": row.get("url", ""),
                    "error": row.get("error", ""),
                }
                failures.append(payload)

            run.failures = failures
            run.save(
                update_fields=[
                    "list_pages_fetched",
                    "detail_pages_fetched",
                    "permits_seen",
                    "permits_new",
                    "permits_updated",
                    "permits_unchanged",
                    "permit_failures",
                    "failures",
                    "updated_at",
                ]
            )

            self.stdout.write(
                f"[{idx}/{len(windows)}] {window_start}..{window_end} "
                f"seen={result.permits_seen} new={result.permits_new} "
                f"updated={result.permits_updated} unchanged={result.permits_unchanged} "
                f"failures={result.permit_failures}"
            )

        run.finished_at = timezone.now()
        run.duration_seconds = round(time.perf_counter() - started, 3)
        run.failures = failures
        run.save(update_fields=["finished_at", "duration_seconds", "failures", "updated_at"])

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley permit backfill completed."))
        self.stdout.write(f"run_id: {run.run_id}")
        self.stdout.write(f"list_pages_fetched: {run.list_pages_fetched}")
        self.stdout.write(f"detail_pages_fetched: {run.detail_pages_fetched}")
        self.stdout.write(f"permits_seen: {run.permits_seen}")
        self.stdout.write(f"permits_new: {run.permits_new}")
        self.stdout.write(f"permits_updated: {run.permits_updated}")
        self.stdout.write(f"permits_unchanged: {run.permits_unchanged}")
        self.stdout.write(f"permit_failures: {run.permit_failures}")
        self.stdout.write(f"duration_seconds: {run.duration_seconds}")
