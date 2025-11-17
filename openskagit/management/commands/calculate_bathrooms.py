from django.core.management.base import BaseCommand
import re

from openskagit.models import Assessor
from openskagit.models import Improvements


HOME_BASE = {
    "MA", "MA1.5", "MA2", "MA2.5",
    "UF", "SW", "MW", "PM",
}

BATH_MAP = {
    "MB": 1.0,
    "FB": 1.0,
    "3QB": 0.75,
    "HB": 0.5,
}


def normalize_code(raw):
    if not raw:
        return ""
    c = raw.strip().upper()
    c = re.sub(r"[A-Z]+$", "", c)
    return c


def is_home_improvement(raw):
    code = normalize_code(raw)
    if code in HOME_BASE:
        return True
    for b in HOME_BASE:
        if code.startswith(b):
            return True
    return False


class Command(BaseCommand):
    help = "Calculate bathrooms from improvement plumbing codes."

    def handle(self, *args, **options):
        self.stdout.write("Calculating bathrooms with normalized improvement codes…")

        # Get improvements that LOOK LIKE home improvements
        improvements = Improvements.objects.filter(
        roll__year=2025).values(
            "parcel_number",
            "plumbing_code",
            "improvement_detail_type_code",
        )

        parcel_bath_totals = {}

        for imp in improvements.iterator(chunk_size=2000):
            raw_code = imp["improvement_detail_type_code"]

            if not is_home_improvement(raw_code):
                continue

            raw_plumbing = (imp["plumbing_code"] or "").strip()
            if not raw_plumbing:
                continue

            parts = [p.strip().upper() for p in raw_plumbing.split(",") if p.strip()]
            bath_value = sum(BATH_MAP.get(p, 0) for p in parts)

            pn = imp["parcel_number"]
            parcel_bath_totals[pn] = parcel_bath_totals.get(pn, 0) + bath_value

        # Update assessor table
        assessors = Assessor.objects.filter(parcel_number__in=list(parcel_bath_totals.keys()))
        updated = 0

        for a in assessors.iterator(chunk_size=1000):
            a.bathrooms = parcel_bath_totals.get(a.parcel_number, 0)
            a.save(update_fields=["bathrooms"])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} assessor rows."))
