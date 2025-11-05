from statistics import median, mean
from datetime import date
from django.core.management.base import BaseCommand
from django.db import transaction
from openskagit.models import Assessor, Sales, NeighborhoodMetrics


SALES_PERIOD_START = date(2024, 5, 1)
SALES_PERIOD_END = date(2025, 4, 30)
MIN_SAMPLE = 5   # keep a few for diagnostics, mark reliability instead of skip

# Residential-only land use codes
RESIDENTIAL_CODES = [
    "110", "111", "112", "113", "120", "130", "140",
    "180", "181", "182", "190", "910", "911", "912"
]


class Command(BaseCommand):
    help = "Calculates official 2025 ratio statistics (COD, PRD, sales ratio) for each neighborhood using valid residential sales only."

    def handle(self, *args, **options):
        updated, skipped = 0, 0

        # Grab all VALID residential sales in the official study period
        base_sales = (
            Sales.objects.filter(
                sale_type="VALID SALE",
                sale_price__gt=0,
                sale_date__range=(SALES_PERIOD_START, SALES_PERIOD_END),
            )
            .values_list("parcel_number", "sale_price")
        )

        sale_map = {}
        for parcel_number, sale_price in base_sales:
            if sale_price and parcel_number:
                sale_map.setdefault(parcel_number.strip(), []).append(float(sale_price))

        # Preload all assessors linked to those parcels
        assessors = Assessor.objects.filter(
            parcel_number__in=sale_map.keys(),
            property_type="R",
            land_use_code__in=RESIDENTIAL_CODES,
            assessed_value__gt=0,
            neighborhood_code__isnull=False,
        )

        # Group assessors by neighborhood
        neighborhoods = {}
        for a in assessors:
            code = (a.neighborhood_code or "").strip().upper()
            neighborhoods.setdefault(code, []).append(a)

        for code, assessor_list in neighborhoods.items():
            ratios, sale_pairs = [], []

            for a in assessor_list:
                sales = sale_map.get(a.parcel_number.strip(), [])
                if not sales:
                    continue
                for sale_price in sales:
                    ratio = a.assessed_value / sale_price
                    if 0.25 <= ratio <= 2.5:
                        ratios.append(ratio)
                        sale_pairs.append((a.assessed_value, sale_price))

            if len(ratios) < MIN_SAMPLE:
                skipped += 1
                continue

            # --- IAAO computations ---
            median_ratio = median(ratios)
            mean_ratio = mean(ratios)
            cod = mean(abs(r - median_ratio) for r in ratios) / median_ratio * 100

            total_assessed = sum(a for a, _ in sale_pairs)
            total_sold = sum(s for _, s in sale_pairs)
            weighted_mean = total_assessed / total_sold if total_sold else None
            prd = (mean_ratio / weighted_mean) if weighted_mean else None

            reliability = (
                "High" if len(ratios) >= 30 else
                "Moderate" if len(ratios) >= 10 else
                "Low"
            )

            with transaction.atomic():
                NeighborhoodMetrics.objects.update_or_create(
                    neighborhood_code=code,
                    year=2025,
                    defaults=dict(
                        sales_ratio=mean_ratio * 100,
                        median_ratio=median_ratio,
                        cod=cod,
                        prd=prd,
                        sample_size=len(ratios),
                        reliability=reliability,
                    ),
                )

            updated += 1
            self.stdout.write(
                f"{code}: {len(ratios)} sales — COD {cod:.2f}, PRD {prd:.3f}, Ratio {mean_ratio*100:.2f}%"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Completed official-window ratio study: {updated} neighborhoods updated, {skipped} skipped (too few sales)."
            )
        )
