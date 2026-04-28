import os
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.db.models.functions import Trim
from django.utils import timezone

from openskagit.models import Assessor, MasterParcel, ParcelOwner


load_dotenv(Path(__file__).resolve().parents[4] / ".env")
os.getenv("DJANGO_SETTINGS_MODULE")


OWNER_FIELDS = (
    "owner_name",
    "owner_add_1",
    "owner_add_2",
    "owner_add_3",
    "owner_city",
    "owner_state",
    "owner_zip",
)


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_owner_payload(assessor):
    return {field: _clean_text(getattr(assessor, field, None)) for field in OWNER_FIELDS}


def _has_owner_payload(payload):
    return any(payload.values())


class Command(BaseCommand):
    help = "Backfill ParcelOwner from the latest Assessor owner record per parcel."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roll-year",
            type=int,
            help="Optional roll year filter. If omitted, uses the latest roll per parcel.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Batch size for create/update operations.",
        )
        parser.add_argument(
            "--include-empty-owner",
            action="store_true",
            help="Include parcels where all owner fields are empty.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Calculate creates/updates without writing rows.",
        )

    def _flush_batch(self, rows, batch_size, dry_run):
        if not rows:
            return 0, 0

        parcel_ids = [parcel_id for parcel_id, _, _ in rows]
        existing_by_parcel = ParcelOwner.objects.filter(parcel_id__in=parcel_ids).in_bulk(
            field_name="parcel_id"
        )

        create_rows = []
        update_rows = []
        now = timezone.now()

        for parcel_id, assessor, payload in rows:
            existing = existing_by_parcel.get(parcel_id)
            if existing is None:
                create_rows.append(
                    ParcelOwner(
                        parcel_id=parcel_id,
                        source_roll_id=assessor.roll_id,
                        source_assessor_id=assessor.id,
                        created_at=now,
                        updated_at=now,
                        **payload,
                    )
                )
                continue

            changed = False
            for field, value in payload.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True

            if existing.source_roll_id != assessor.roll_id:
                existing.source_roll_id = assessor.roll_id
                changed = True

            if existing.source_assessor_id != assessor.id:
                existing.source_assessor_id = assessor.id
                changed = True

            if changed:
                existing.updated_at = now
                update_rows.append(existing)

        if dry_run:
            return len(create_rows), len(update_rows)

        with transaction.atomic():
            if create_rows:
                ParcelOwner.objects.bulk_create(create_rows, batch_size=batch_size)
            if update_rows:
                ParcelOwner.objects.bulk_update(
                    update_rows,
                    fields=[
                        "owner_name",
                        "owner_add_1",
                        "owner_add_2",
                        "owner_add_3",
                        "owner_city",
                        "owner_state",
                        "owner_zip",
                        "source_roll",
                        "source_assessor",
                        "updated_at",
                    ],
                    batch_size=batch_size,
                )

        return len(create_rows), len(update_rows)

    def handle(self, *args, **options):
        roll_year = options["roll_year"]
        batch_size = options["batch_size"]
        include_empty_owner = options["include_empty_owner"]
        dry_run = options["dry_run"]

        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1")

        if ParcelOwner._meta.db_table not in connection.introspection.table_names():
            raise CommandError(
                "parcel_owner table does not exist. Run `python3 manage.py migrate openskagit` first."
            )

        latest_assessor = Assessor.objects.annotate(parcel_key=Trim("parcel_number")).exclude(
            parcel_key=""
        )

        if roll_year is not None:
            latest_assessor = latest_assessor.filter(roll__year=roll_year)

        latest_assessor = latest_assessor.annotate(
            has_master_parcel=Exists(
                MasterParcel.objects.filter(parcel_number=OuterRef("parcel_key"))
            )
        ).filter(has_master_parcel=True)

        if roll_year is None:
            latest_assessor = latest_assessor.order_by("parcel_key", "-roll__year", "-id").distinct(
                "parcel_key"
            )
        else:
            latest_assessor = latest_assessor.order_by("parcel_key", "-id").distinct("parcel_key")

        total_candidates = latest_assessor.count()
        if total_candidates == 0:
            self.stdout.write(self.style.WARNING("No eligible assessor rows found for backfill."))
            return

        self.stdout.write(
            f"Processing {total_candidates} parcel owner candidates "
            f"(roll_year={roll_year or 'latest'}, dry_run={dry_run})"
        )

        processed = 0
        skipped_empty = 0
        created = 0
        updated = 0
        batch_rows = []

        for assessor in latest_assessor.select_related("roll").iterator(chunk_size=batch_size):
            processed += 1

            parcel_id = _clean_text(getattr(assessor, "parcel_key", assessor.parcel_number))
            if not parcel_id:
                continue

            payload = _build_owner_payload(assessor)
            if not include_empty_owner and not _has_owner_payload(payload):
                skipped_empty += 1
                continue

            batch_rows.append((parcel_id, assessor, payload))

            if len(batch_rows) >= batch_size:
                c_count, u_count = self._flush_batch(batch_rows, batch_size=batch_size, dry_run=dry_run)
                created += c_count
                updated += u_count
                batch_rows = []
                self.stdout.write(
                    f"Processed {processed}/{total_candidates} | created={created} updated={updated} skipped_empty={skipped_empty}"
                )

        if batch_rows:
            c_count, u_count = self._flush_batch(batch_rows, batch_size=batch_size, dry_run=dry_run)
            created += c_count
            updated += u_count

        summary = (
            f"Done. processed={processed} created={created} updated={updated} skipped_empty={skipped_empty}"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run only. {summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
