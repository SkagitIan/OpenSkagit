# openskagit/management/commands/split_neighborhood_codes.py

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import Parcel

# Example input:
# "(20SWNSKAGT) SEDRO WOOLLEY RESIDENTIAL NORTH SKAGIT (LYMAN/HAMILTON)"
# -> neighborhood_code: "20SWNSKAGT"
# -> neighborhood_description: "SEDRO WOOLLEY RESIDENTIAL NORTH SKAGIT (LYMAN/HAMILTON)"

PATTERN = re.compile(r'^\s*\((?P<code>[^)]+)\)\s*(?P<desc>.*)$')


class Command(BaseCommand):
    help = "Split neighborhood_code into code + description fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional: limit how many parcels to process.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")

        qs = Parcel.objects.exclude(neighborhood_code__isnull=True).exclude(
            neighborhood_code__exact=""
        )

        # Only touch rows where description is still empty
        qs = qs.filter(neighborhood_description__isnull=True)

        if limit:
            qs = qs[:limit]

        updated = 0
        skipped = 0

        self.stdout.write(
            self.style.NOTICE(f"Processing {qs.count()} Parcel rows...")
        )

        with transaction.atomic():
            for parcel in qs.iterator():
                raw = parcel.neighborhood_code
                match = PATTERN.match(raw)
                if not match:
                    skipped += 1
                    continue

                code = match.group("code").strip()
                desc = match.group("desc").strip() or None

                parcel.neighborhood_code = code
                parcel.neighborhood_description = desc
                parcel.save(
                    update_fields=["neighborhood_code", "neighborhood_description"]
                )
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Updated {updated} parcels, skipped {skipped} that didn't match pattern."
            )
        )
