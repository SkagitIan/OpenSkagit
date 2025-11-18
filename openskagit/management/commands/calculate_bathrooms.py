from django.core.management.base import BaseCommand
from django.db.models import Q
import re

from openskagit.models import Assessor, Improvements


HOME_BASE = {
    "MA", "MA1.5", "MA2", "MA2.5",
    "UF", "SW", "MW", "PM",
}

BATH_MAP = {
    "MB": 1.0,
    "FB": 1.0,
    "2FB": 2.0,
    "3FB": 3.0, 
    "3QB": 0.75,
    "HB": 0.5,
    "2HB": 1.0, 
}


def normalize_code(raw):
    if not raw:
        return ""
    c = raw.strip().upper()
    c = re.sub(r"[A-Z]+$", "", c)
    return c


class Command(BaseCommand):
    help = "Calculate bathrooms from improvement plumbing codes (roll=2025)."

    def handle(self, *args, **options):
        self.stdout.write("Calculating bathrooms for roll=2025…")

        # Push as much filtering into SQL as possible
        home_prefix_filter = (
              Q(improvement_detail_type_code__istartswith="MA")
            | Q(improvement_detail_type_code__istartswith="MA1.5")
            | Q(improvement_detail_type_code__istartswith="MA2")
            | Q(improvement_detail_type_code__istartswith="MA2.5")
            | Q(improvement_detail_type_code__istartswith="UF")
            | Q(improvement_detail_type_code__istartswith="SW")
            | Q(improvement_detail_type_code__istartswith="MW")
            | Q(improvement_detail_type_code__istartswith="PM")
        )

        improvements = (
            Improvements.objects
            .filter(roll__year=2025)
            .filter(home_prefix_filter)
            .values("parcel_number", "plumbing_code", "improvement_detail_type_code")
        )

        parcel_bath_totals = {}

        for imp in improvements.iterator(chunk_size=5000):
            raw_plumbing = (imp["plumbing_code"] or "").strip()
            if not raw_plumbing:
                continue

            parts = [p.strip().upper() for p in raw_plumbing.split(",") if p.strip()]
            bath_value = sum(BATH_MAP.get(p, 0) for p in parts)

            pn = imp["parcel_number"]
            parcel_bath_totals[pn] = parcel_bath_totals.get(pn, 0) + bath_value

        parcel_numbers = parcel_bath_totals.keys()

        assessors = Assessor.objects.filter(
            roll__year=2025,
            parcel_number__in=parcel_numbers
        )

        batch = []
        for a in assessors:
            a.bathrooms = parcel_bath_totals[a.parcel_number]
            batch.append(a)

        Assessor.objects.bulk_update(batch, ["bathrooms"], batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"Updated {len(batch)} assessor rows."))
