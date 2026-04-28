from pathlib import Path

from django.core.management.base import BaseCommand
from dotenv import load_dotenv

from legal_code.scrapers.snapshots import (
    parse_anacortes_html_snapshot,
    parse_burlington_pdf_snapshot,
)
from legal_code.services import LegalIngestService

load_dotenv()

DEFAULT_ANACORTES_PATH = Path("data/anacortes/anacortes_code.html")
DEFAULT_BURLINGTON_PATH = Path("data/burlington/burlington.pdf")


class Command(BaseCommand):
    help = "Ingest local legal code snapshots for Anacortes HTML and Burlington PDF"

    def add_arguments(self, parser):
        parser.add_argument(
            "--jurisdiction",
            type=str,
            default="all",
            choices=["all", "anacortes", "burlington"],
            help="Which snapshot jurisdiction to ingest",
        )
        parser.add_argument(
            "--anacortes-path",
            type=str,
            default=str(DEFAULT_ANACORTES_PATH),
            help="Path to Anacortes HTML snapshot",
        )
        parser.add_argument(
            "--burlington-path",
            type=str,
            default=str(DEFAULT_BURLINGTON_PATH),
            help="Path to Burlington PDF snapshot",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and compute ingest summary without writing DB rows",
        )
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stop on first ingest error",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional max section records to ingest from each source",
        )

    def handle(self, *args, **options):
        jurisdiction = options["jurisdiction"]
        anacortes_path = Path(options["anacortes_path"])
        burlington_path = Path(options["burlington_path"])
        dry_run = bool(options["dry_run"])
        fail_fast = bool(options["fail_fast"])
        limit = options["limit"]

        all_sections = []

        if jurisdiction in {"all", "anacortes"}:
            if not anacortes_path.exists():
                raise RuntimeError(f"Anacortes snapshot not found: {anacortes_path}")
            self.stdout.write(f"Parsing Anacortes snapshot: {anacortes_path}")
            anacortes_sections = parse_anacortes_html_snapshot(anacortes_path)
            if limit is not None:
                anacortes_sections = anacortes_sections[: max(0, limit)]
            self.stdout.write(f"Anacortes sections parsed: {len(anacortes_sections)}")
            all_sections.extend(anacortes_sections)

        if jurisdiction in {"all", "burlington"}:
            if not burlington_path.exists():
                raise RuntimeError(f"Burlington snapshot not found: {burlington_path}")
            self.stdout.write(f"Parsing Burlington snapshot: {burlington_path}")
            burlington_sections = parse_burlington_pdf_snapshot(burlington_path)
            if limit is not None:
                burlington_sections = burlington_sections[: max(0, limit)]
            self.stdout.write(f"Burlington sections parsed: {len(burlington_sections)}")
            all_sections.extend(burlington_sections)

        if not all_sections:
            self.stdout.write(self.style.WARNING("No sections parsed; nothing to ingest."))
            return

        service = LegalIngestService()
        summary = service.ingest_sections(
            all_sections,
            dry_run=dry_run,
            fail_fast=fail_fast,
        )

        self.stdout.write(self.style.SUCCESS("Snapshot ingest completed."))
        for key, value in summary.as_dict().items():
            self.stdout.write(f"{key}: {value}")
