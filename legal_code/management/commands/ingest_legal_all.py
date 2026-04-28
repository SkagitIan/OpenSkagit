from django.core.management.base import BaseCommand, CommandError
from dotenv import load_dotenv

from legal_code.scrapers import ScraperError
from legal_code.services import IngestSummary

from ._legal_ingest import (
    merge_summaries,
    resolve_requested_jurisdictions,
    run_ingest_for_jurisdiction,
    scraper_error_message,
    summary_lines,
)

load_dotenv()


class Command(BaseCommand):
    help = "Scrape and ingest multiple jurisdictions with Playwright"

    def add_arguments(self, parser):
        parser.add_argument(
            "--jurisdiction",
            action="append",
            default=None,
            help="Optional jurisdiction slug or alias. Repeat flag to pass multiple.",
        )
        parser.add_argument(
            "--limit-per-jurisdiction",
            type=int,
            default=None,
            help="Optional max pages/docs to scrape per jurisdiction",
        )
        parser.add_argument(
            "--headful",
            action="store_true",
            help="Run browser in visible (non-headless) mode",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Scrape and compute ingest summaries without writing DB rows",
        )
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stop command on first jurisdiction scrape/ingest error",
        )

    def handle(self, *args, **options):
        limit = options["limit_per_jurisdiction"]
        if limit is not None and limit < 1:
            raise CommandError("--limit-per-jurisdiction must be >= 1")

        jurisdictions = resolve_requested_jurisdictions(options["jurisdiction"])
        dry_run = bool(options["dry_run"])
        headful = bool(options["headful"])
        fail_fast = bool(options["fail_fast"])

        aggregate = IngestSummary()
        total_scraped = 0
        failures: list[str] = []

        self.stdout.write(f"Jurisdictions selected: {len(jurisdictions)}")
        self.stdout.write(f"Dry run: {dry_run}")

        for jurisdiction in jurisdictions:
            self.stdout.write(f"Running: {jurisdiction.slug} ({jurisdiction.publisher})")
            try:
                scraped_count, summary = run_ingest_for_jurisdiction(
                    jurisdiction=jurisdiction,
                    limit=limit,
                    headful=headful,
                    dry_run=dry_run,
                    fail_fast=fail_fast,
                )
            except ScraperError as exc:
                message = scraper_error_message(jurisdiction=jurisdiction, error=exc)
                failures.append(message)
                self.stderr.write(self.style.WARNING(message))
                if fail_fast:
                    raise CommandError(message) from exc
                continue

            total_scraped += scraped_count
            merge_summaries(aggregate, summary)

            self.stdout.write(f"{jurisdiction.slug}.sections_scraped: {scraped_count}")
            for line in summary_lines(summary):
                self.stdout.write(f"{jurisdiction.slug}.{line}")

        self.stdout.write(self.style.SUCCESS("All-jurisdiction ingest run completed."))
        self.stdout.write(f"jurisdictions_attempted: {len(jurisdictions)}")
        self.stdout.write(f"jurisdictions_succeeded: {len(jurisdictions) - len(failures)}")
        self.stdout.write(f"sections_scraped_total: {total_scraped}")
        for line in summary_lines(aggregate):
            self.stdout.write(f"aggregate.{line}")

        if failures:
            self.stderr.write(self.style.WARNING(f"Failed jurisdictions: {len(failures)}"))
            for failure in failures:
                self.stderr.write(self.style.WARNING(f"failure: {failure}"))
