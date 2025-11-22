from django.core.management.base import BaseCommand
from django.db.models import Sum
from openskagit.models import Assessor, Land

ACRE_IN_SQFT = 43560.0


class Command(BaseCommand):
    """
    Backfill Assessor.acres from the Land table.

    OPTIMIZED VERSION:
    - Uses .iterator() to avoid loading all objects into memory.
    - Uses .bulk_update() to reduce database write operations by ~1000x.
    """

    help = "Backfill Assessor.acres from Land.size_acres / size_square_feet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only update Assessor rows where acres is NULL or 0.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of Assessor rows to update per SQL statement.",
        )

    def handle(self, *args, **options):
        only_missing = options["only_missing"]
        batch_size = options["batch_size"]

        # --- STEP 1: Aggregate Land Data (Keep existing logic) ---
        self.stdout.write("Aggregating land sizes by roll and parcel…")

        land_aggs = (
            Land.objects.values("roll_id", "parcel_number")
            .annotate(
                total_acres=Sum("size_acres"),
                total_sqft=Sum("size_square_feet"),
            )
        )

        # Build a lookup dict: (roll_id, parcel_number) -> acres
        land_lookup = {}
        for row in land_aggs:
            roll_id = row["roll_id"]
            parcel = (row["parcel_number"] or "").strip()
            if not roll_id or not parcel:
                continue

            acres = row["total_acres"] or 0.0
            sqft = row["total_sqft"] or 0.0

            if (not acres) and sqft:
                acres = sqft / ACRE_IN_SQFT

            # Skip if we still don't have anything meaningful
            if not acres or acres <= 0:
                continue

            land_lookup[(roll_id, parcel)] = float(acres)

        self.stdout.write(f"Built land lookup for {len(land_lookup)} roll/parcel combos.")

        # --- STEP 2: Prepare Assessor QuerySet ---
        qs = Assessor.objects.all().order_by("id")
        if only_missing:
            qs = qs.filter(acres__isnull=True) | qs.filter(acres__lte=0)

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No Assessor rows to update."))
            return

        self.stdout.write(f"Scanning {total} Assessor rows for updates…")

        # --- STEP 3: Iterate and Bulk Update ---
        update_batch = []
        processed = 0
        updated_total = 0

        # .iterator() streams rows from the DB instead of loading them all at once.
        # chunk_size determines how many rows Django fetches from the DB cursor at a time.
        for assessor in qs.iterator(chunk_size=2000):
            processed += 1
            
            key = (assessor.roll_id, (assessor.parcel_number or "").strip())
            new_acres = land_lookup.get(key)

            # 1. Check if we found a match
            if new_acres is None:
                continue

            # 2. If only_missing, ensure we aren't overwriting valid data
            # (Double check here in case the DB filter missed edge cases, strictly safe)
            if only_missing and assessor.acres and assessor.acres > 0:
                continue

            # 3. Skip if value is essentially the same to avoid unnecessary writes
            if assessor.acres is not None and abs(assessor.acres - new_acres) < 1e-4:
                continue

            # 4. Stage the change
            assessor.acres = new_acres
            update_batch.append(assessor)

            # 5. Execute Bulk Update when batch is full
            if len(update_batch) >= batch_size:
                Assessor.objects.bulk_update(update_batch, ["acres"])
                updated_total += len(update_batch)
                self.stdout.write(
                    f"Processed {processed}/{total} | Updated {updated_total} so far..."
                )
                update_batch = []  # Clear list for next batch

        # --- STEP 4: Flush remaining items ---
        if update_batch:
            Assessor.objects.bulk_update(update_batch, ["acres"])
            updated_total += len(update_batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {processed} rows. Updated acres on {updated_total} Assessor rows."
            )
        )