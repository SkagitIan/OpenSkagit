from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import (
    MasterParcel,
    ParcelPlanningFacts,
    ParcelWaterfacts,
    ParcelGeometry,
    ParcelDevelopmentProfile,
)
from openskagit.services.development_profile import classify_development_form


class Command(BaseCommand):
    help = "Build Parcel Development Profiles (PDP)"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)
        parser.add_argument("--parcel", type=str)
        parser.add_argument(
            "--landuse",
            type=str,
            help="Optional assessor land-use code (e.g. 110)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        qs = MasterParcel.objects.filter(proptype="R")

        # Optional land-use filter (string-safe)
        if options.get("landuse"):
            qs = qs.filter(land_use_code=str(options["landuse"]))

        if options.get("parcel"):
            qs = qs.filter(parcel_number=options["parcel"])

        if options.get("limit"):
            qs = qs[: options["limit"]]

        created = updated = 0

        for parcel in qs.iterator():
            planning = ParcelPlanningFacts.objects.filter(
                parcel_id=parcel.parcel_number
            ).first()

            water = ParcelWaterfacts.objects.filter(
                parcel_number=parcel.parcel_number
            ).first()

            geometry = ParcelGeometry.objects.filter(
                parcel=parcel
            ).first()

            (
                form,
                context,
                confidence,
                reasons,
                constraints,
            ) = classify_development_form(
                parcel,
                planning,
                water,
                geometry,
            )

            _, is_created = ParcelDevelopmentProfile.objects.update_or_create(
                parcel=parcel,
                defaults={
                    "primary_development_form": form,
                    "development_context": context,
                    "confidence": confidence,
                    "reasons": reasons,
                    "development_constraints": constraints,
                },
            )

            created += int(is_created)
            updated += int(not is_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"PDP build complete — created: {created}, updated: {updated}"
            )
        )
