from django.core.management.base import BaseCommand
from openskagit.models import Assessor, Parcel

class Command(BaseCommand):
    help = "Create or update Parcel records from existing Assessor data."

    def handle(self, *args, **options):
        created, updated = 0, 0
        seen = set()

        qs = (
            Assessor.objects
            .values_list("parcel_number", "address", "neighborhood_code", "land_use_code", "property_type")
            .distinct()
        )

        for pn, addr, nbhd, land_use, prop_type in qs:
            if not pn or pn in seen:
                continue
            seen.add(pn)

            obj, created_flag = Parcel.objects.update_or_create(
                parcel_number=pn,
                defaults={
                    "address": addr,
                    "neighborhood_code": nbhd,
                    "land_use_code": land_use,
                    "property_type": (prop_type or "R")[:1],
                },
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Parcels loaded. Created: {created}, Updated: {updated}"
        ))
