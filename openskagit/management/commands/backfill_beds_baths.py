from django.core.management.base import BaseCommand
from django.db import transaction
from openskagit.models import Assessor, Improvements, AssessmentRoll
import re

def parse_numeric(value):
    """Convert weird bed/bath strings into a numeric float."""
    if value is None:
        return None

    # Convert to string and normalize
    s = str(value).strip().lower()

    # Quick patterns first
    if s in {"na", "n/a", "none", "", "0"}:
        return None

    # Replace fractional patterns
    s = s.replace("¾", "3/4").replace("¼", "1/4")

    # Common fractional shorthand
    s = s.replace("3qb", "3/4").replace("3q", "3/4").replace("q", "0.25")

    # Try to find standard fraction patterns like 3/4 or 1/2
    fraction_match = re.search(r"(\d+)\s*/\s*(\d+)", s)
    if fraction_match:
        num, den = fraction_match.groups()
        try:
            return round(float(num) / float(den), 2)
        except ZeroDivisionError:
            return None

    # Extract digits
    digit_match = re.search(r"(\d+(\.\d+)?)", s)
    if digit_match:
        try:
            return float(digit_match.group(1))
        except ValueError:
            pass

    return None


class Command(BaseCommand):
    help = "Backfill missing bedrooms/bathrooms in Assessor records from Improvements (2025 → 2024 fallback)."

    def handle(self, *args, **options):
        roll_2025 = AssessmentRoll.objects.filter(year=2025).first()
        roll_2024 = AssessmentRoll.objects.filter(year=2024).first()

        if not roll_2025 or not roll_2024:
            self.stderr.write("❌ Missing one or both rolls for 2024/2025.")
            return

        assessors = Assessor.objects.filter(roll=roll_2025, bedrooms__isnull=True, bathrooms__isnull=True)
        total = assessors.count()
        updated = 0

        self.stdout.write(f"🔍 Found {total} assessor records missing bed/bath data...")

        for assessor in assessors.iterator(chunk_size=500):
            parcel = assessor.parcel_number.strip() if assessor.parcel_number else None
            if not parcel:
                continue

            # Try 2025 improvements first
            imp = Improvements.objects.filter(roll=roll_2025, parcel_number=parcel).first()

            # Fall back to 2024
            if not imp:
                imp = Improvements.objects.filter(roll=roll_2024, parcel_number=parcel).first()

            if not imp:
                continue

            beds = parse_numeric(imp.bedrooms)
            baths = parse_numeric(imp.plumbing_code) or parse_numeric(imp.rooms)

            # If we got anything valid, save
            if beds or baths:
                assessor.bedrooms = beds or assessor.bedrooms
                assessor.bathrooms = baths or assessor.bathrooms
                with transaction.atomic():
                    assessor.save(update_fields=["bedrooms", "bathrooms"])
                updated += 1

        self.stdout.write(f"✅ Updated {updated} / {total} assessor records.")
