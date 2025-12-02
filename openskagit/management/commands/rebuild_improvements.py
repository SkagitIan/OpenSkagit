from django.core.management.base import BaseCommand, CommandError

from openskagit.improvements_etl import run_improvements_etl


class Command(BaseCommand):
    help = "Rebuild parcel-level improvement rollups and enrichment for a given roll year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roll",
            type=int,
            default=2025,
            help="Assessment roll year to process (default: 2025).",
        )
        parser.add_argument(
            "--parcel",
            type=str,
            help="Optional parcel_number filter (e.g., P12346) to scope the run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute aggregates without writing updates.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Bulk update batch size for assessor rows.",
        )

    def handle(self, *args, **options):
        roll_year = options["roll"]
        parcel = options.get("parcel")
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        try:
            result = run_improvements_etl(
                roll_year=roll_year,
                parcel=parcel,
                dry_run=dry_run,
                batch_size=batch_size,
                stdout=self.stdout,
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        scope = f"parcel {parcel}" if parcel else "all parcels"
        self.stdout.write(self.style.SUCCESS(f"Finished improvements ETL for roll {roll_year} ({scope})."))
        self.stdout.write(
            f"Improvements processed: {result['improvements_processed']} | "
            f"Parcels aggregated: {result['parcels_aggregated']} | "
            f"Assessors processed: {result['assessors_processed']} | "
            f"Assessor rows {'touched' if dry_run else 'updated'}: {result['assessors_updated']}"
        )
