from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit.models import MasterParcel, ParcelOwner, SedroWoolleyPermit


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


def _extract_parcel_number(raw_payload: Any) -> str:
    if not isinstance(raw_payload, dict):
        return ""
    detail = raw_payload.get("detail")
    summary = raw_payload.get("summary")
    if isinstance(detail, dict):
        parcel_number = str(detail.get("parcel_number") or "").strip()
        if parcel_number:
            return parcel_number
    if isinstance(summary, dict):
        parcel_number = str(summary.get("parcel_number") or "").strip()
        if parcel_number:
            return parcel_number
    return ""


class Command(BaseCommand):
    help = "Backfill Sedro-Woolley permit parcel/owner foreign keys from raw payload parcel numbers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process all permits instead of only permits with null parcel FK.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Optional max number of permits to process.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Bulk update batch size (default: 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing updates.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        batch_size = options.get("batch_size") or 500
        process_all = bool(options.get("all"))
        dry_run = bool(options.get("dry_run"))

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1 when provided.")
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")

        qs = SedroWoolleyPermit.objects.all().order_by("id").only("id", "raw_payload", "parcel_id", "owner_id")
        if not process_all:
            qs = qs.filter(parcel__isnull=True)
        if limit is not None:
            qs = qs[:limit]

        permits = list(qs)
        if not permits:
            self.stdout.write(self.style.WARNING("No Sedro-Woolley permits matched the backfill filter."))
            return

        parcel_candidates = {
            parcel_number
            for parcel_number in (_extract_parcel_number(permit.raw_payload) for permit in permits)
            if parcel_number
        }
        valid_parcels = set(
            MasterParcel.objects.filter(parcel_number__in=parcel_candidates).values_list("parcel_number", flat=True)
        )
        owner_by_parcel = dict(
            ParcelOwner.objects.filter(parcel_id__in=valid_parcels).values_list("parcel_id", "id")
        )

        updates: list[SedroWoolleyPermit] = []
        unchanged = 0
        missing_parcel_number = 0
        unmatched_parcel = 0

        for permit in permits:
            raw_parcel_number = _extract_parcel_number(permit.raw_payload)
            if not raw_parcel_number:
                missing_parcel_number += 1
                continue

            parcel_id = raw_parcel_number if raw_parcel_number in valid_parcels else None
            if parcel_id is None:
                unmatched_parcel += 1
            owner_id = owner_by_parcel.get(parcel_id) if parcel_id else None

            if permit.parcel_id == parcel_id and permit.owner_id == owner_id:
                unchanged += 1
                continue

            permit.parcel_id = parcel_id
            permit.owner_id = owner_id
            updates.append(permit)

        self.stdout.write(f"permits_scanned: {len(permits)}")
        self.stdout.write(f"updates_needed: {len(updates)}")
        self.stdout.write(f"unchanged: {unchanged}")
        self.stdout.write(f"missing_parcel_number_in_payload: {missing_parcel_number}")
        self.stdout.write(f"parcel_number_not_in_master_parcel: {unmatched_parcel}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run only; no updates written."))
            return

        if updates:
            SedroWoolleyPermit.objects.bulk_update(updates, ["parcel", "owner"], batch_size=batch_size)
            self.stdout.write(self.style.SUCCESS(f"Updated {len(updates)} Sedro-Woolley permits."))
        else:
            self.stdout.write(self.style.SUCCESS("No updates were required."))
