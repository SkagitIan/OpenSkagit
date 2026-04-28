from django.core.management.base import BaseCommand, CommandError
from dotenv import load_dotenv

from legal_code.scrapers import ScraperError

from ._legal_ingest import (
    resolve_single_jurisdiction,
    run_ingest_for_jurisdiction,
    scraper_error_message,
    summary_lines,
)

load_dotenv()


class Command(BaseCommand):
    help = "Scrape one jurisdiction with Playwright and ingest into legal_code models"

    def add_arguments(self, parser):
        parser.add_argument(
            "--jurisdiction",
            type=str,
            required=True,
            help="Jurisdiction slug or alias",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional max pages/docs to scrape for this run",
        )
        parser.add_argument(
            "--headful",
            action="store_true",
            help="Run browser in visible (non-headless) mode",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Scrape and compute ingest summary without writing DB rows",
        )
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stop ingest on first section-level error",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be >= 1")

        jurisdiction = resolve_single_jurisdiction(options["jurisdiction"])
        dry_run = bool(options["dry_run"])
        headful = bool(options["headful"])
        fail_fast = bool(options["fail_fast"])

        self.stdout.write(f"Jurisdiction: {jurisdiction.slug}")
        self.stdout.write(f"Publisher: {jurisdiction.publisher}")
        self.stdout.write(f"Dry run: {dry_run}")

        try:
            scraped_count, summary = run_ingest_for_jurisdiction(
                jurisdiction=jurisdiction,
                limit=limit,
                headful=headful,
                dry_run=dry_run,
                fail_fast=fail_fast,
            )
        except ScraperError as exc:
            raise CommandError(scraper_error_message(jurisdiction=jurisdiction, error=exc)) from exc

        self.stdout.write(self.style.SUCCESS("Jurisdiction ingest completed."))
        self.stdout.write(f"sections_scraped: {scraped_count}")
        for line in summary_lines(summary):
            self.stdout.write(line)
