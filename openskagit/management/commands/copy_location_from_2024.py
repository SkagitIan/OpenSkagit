from django.core.management.base import BaseCommand
from django.db import connection
from openskagit.models import AssessmentRoll

class Command(BaseCommand):
    help = "Copy geometry and coordinates from 2024 roll to 2025 roll (parcel matches only)."

    def handle(self, *args, **options):
        roll_2025 = AssessmentRoll.objects.get(year=2025)
        roll_2024 = AssessmentRoll.objects.get(year=2024)

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE assessor AS new
                   SET geom = old.geom,
                       latitude = old.latitude,
                       longitude = old.longitude
                  FROM assessor AS old
                 WHERE new.parcel_number = old.parcel_number
                   AND new.roll_id = %s
                   AND old.roll_id = %s
                   AND new.geom IS NULL
                   AND old.geom IS NOT NULL;
            """, [roll_2025.id, roll_2024.id])

            count = cursor.rowcount

        self.stdout.write(f"✅ Copied geometry for {count} parcels from {roll_2024.year} to {roll_2025.year}.")
