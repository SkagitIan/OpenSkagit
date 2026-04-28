from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from openskagit.services.sedro_woolley_pdf_ingest import (
    SedroWoolleyPdfIngestor,
    find_sw_pdf_source_records,
)


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = (
        "Ingest crawled Sedro-Woolley PDFs into markdown/json/chunk artifacts "
        "for downstream RAG workflows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            help="Specific crawl run id to ingest (defaults to latest crawl run).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Max number of PDFs to ingest.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="Number of concurrent PDF ingest workers.",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Skip PDFs that already have document.json artifacts.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild artifacts even if output files already exist.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Enumerate ingest targets and write ingest manifest without extracting PDFs.",
        )
        parser.add_argument(
            "--enable-ocr",
            action="store_true",
            help="Enable OCR fallback for pages without text layer (requires pdf2image + pytesseract).",
        )
        parser.add_argument(
            "--extract-tables",
            action="store_true",
            help="Explicitly enable table extraction (enabled by default).",
        )
        parser.add_argument(
            "--skip-tables",
            action="store_true",
            help="Disable table extraction.",
        )
        parser.add_argument(
            "--chunk-chars",
            type=int,
            default=1800,
            help="Approximate max chars per RAG chunk.",
        )
        parser.add_argument(
            "--media-root",
            help="Override media root directory (defaults to Django MEDIA_ROOT).",
        )

    def handle(self, *args, **options):
        workers = options["workers"]
        limit = options.get("limit")
        chunk_chars = options["chunk_chars"]
        dry_run = options["dry_run"]
        extract_tables = True
        if options["skip_tables"]:
            extract_tables = False
        elif options["extract_tables"]:
            extract_tables = True

        if workers < 1:
            raise CommandError("--workers must be at least 1")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if chunk_chars < 300:
            raise CommandError("--chunk-chars must be at least 300")

        if options.get("media_root"):
            media_root = Path(options["media_root"]).expanduser()
        else:
            media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)

        source_records = find_sw_pdf_source_records(
            media_root=media_root,
            run_id=options.get("run_id"),
            limit=limit,
        )
        if not source_records:
            self.stdout.write(self.style.WARNING("No PDF crawl records found to ingest."))
            return

        if not dry_run:
            try:
                import pypdf  # noqa: F401
            except Exception as exc:
                raise CommandError(
                    "pypdf is required for PDF ingest. Install dependencies before running this command."
                ) from exc

        ingestor = SedroWoolleyPdfIngestor(
            media_root=media_root,
            workers=workers,
            resume=options["resume"],
            force=options["force"],
            dry_run=dry_run,
            enable_ocr=options["enable_ocr"],
            extract_tables=extract_tables,
            chunk_chars=chunk_chars,
        )
        summary = ingestor.ingest(
            run_id=options.get("run_id"),
            limit=limit,
        )
        payload = summary.to_dict()

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley PDF ingest completed."))
        self.stdout.write(f"ingest_run_id: {payload['run_id']}")
        self.stdout.write(f"source_run_id: {payload['source_run_id']}")
        self.stdout.write(f"records_found: {payload['records_found']}")
        self.stdout.write(f"processed_count: {payload['processed_count']}")
        self.stdout.write(f"success_count: {payload['success_count']}")
        self.stdout.write(f"dry_run_count: {payload['dry_run_count']}")
        self.stdout.write(f"skipped_count: {payload['skipped_count']}")
        self.stdout.write(f"failed_count: {payload['failed_count']}")
        self.stdout.write(f"chunks_written: {payload['chunks_written']}")
        self.stdout.write(f"chunks_path: {payload['chunks_path']}")
        self.stdout.write(f"manifest_path: {payload['manifest_path']}")
        self.stdout.write(f"run_summary_path: {payload['run_summary_path']}")
        self.stdout.write(f"table_engine: {payload['table_engine']}")
        self.stdout.write(f"ocr_enabled: {payload['enable_ocr']}")
        self.stdout.write(f"ocr_available: {payload['ocr_available']}")

        failures = payload.get("failures") or []
        if failures:
            self.stdout.write(self.style.WARNING("Sample failures:"))
            for row in failures[:10]:
                self.stdout.write(f"- {row.get('url')} :: {row.get('error')}")
