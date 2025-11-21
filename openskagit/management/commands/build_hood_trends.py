import sys
from collections import defaultdict
from typing import Dict, List, Tuple

import numpy as np  # <--- Optimization Engine

from django.core.management.base import BaseCommand
from django.db import transaction, models

from openskagit.models import ParcelHistory, NeighborhoodTrend

IMPORTANT_PREFIXES = [
    "20MV", "21MV", "22MV", "23MV",
    "20LC", "21LC", "22LC", "23LC",
    "20B", "21B", "22B", "23B", "26B", "27B",
    "20A", "21A", "22A", "23A", "20FID", "22FID", "20GUEM", "22GUEM",
    "20SW", "21SW", "22SW", "23SW",
    "20CC", "22CC", "10CC",
]

TARGET_ROLL_YEAR = 2025

# Pre-compiled translation table to strip money characters instantly
REMOVE_CHARS = str.maketrans("", "", "$,")

def parse_money_fast(raw: object) -> int | None:
    """
    Optimized parser using string translation and optimistic typing.
    """
    if raw is None:
        return None
    
    # Fast path for existing numbers
    if isinstance(raw, (int, float)):
        return int(raw + 0.5)

    s = str(raw)
    if not s or s == "$0" or s == "0":
        return 0
        
    # Fast string cleanup
    clean_s = s.translate(REMOVE_CHARS)
    
    if not clean_s:
        return 0

    try:
        # int(float()) handles "1200.00" which int() alone chokes on
        return int(float(clean_s) + 0.5)
    except ValueError:
        return None


class YearBucket:
    __slots__ = ("land", "building", "total", "tax")

    def __init__(self):
        # We keep these as lists for fast appending during the loop.
        # We will convert to numpy arrays only during the calculation phase.
        self.land = []
        self.building = []
        self.total = []
        self.tax = []


class Command(BaseCommand):
    help = "Build NeighborhoodTrend rows using NumPy optimization."

    def add_arguments(self, parser):
        parser.add_argument("--hood", help="Optional prefix filter")

    def handle(self, *args, **options):
        hood_prefix = options.get("hood")
        
        self.stdout.write(self.style.MIGRATE_HEADING("Building Trends (NumPy Optimized)..."))

        # ------------------------------------------------------------------
        # 1. Efficient Database Fetching
        # ------------------------------------------------------------------
        base_qs = ParcelHistory.objects.all().exclude(neighborhood_code__isnull=True).exclude(neighborhood_code="")

        if hood_prefix:
            base_qs = base_qs.filter(neighborhood_code__startswith=hood_prefix)
            target_prefixes = [hood_prefix]
        else:
            q = models.Q()
            for p in IMPORTANT_PREFIXES:
                q |= models.Q(neighborhood_code__startswith=p)
            base_qs = base_qs.filter(q)
            target_prefixes = IMPORTANT_PREFIXES

        # OPTIMIZATION: Only fetch the 2 columns we actually need
        base_qs = base_qs.only("neighborhood_code", "rows")

        total_ph = base_qs.count()
        self.stdout.write(f"Scanning {total_ph} parcels...")

        if total_ph == 0:
            return

        buckets: Dict[Tuple[str, int], YearBucket] = defaultdict(YearBucket)
        hood_years: defaultdict[str, set] = defaultdict(set)
        
        processed = 0

        # ------------------------------------------------------------------
        # 2. Data Ingestion (The Map Phase)
        # ------------------------------------------------------------------
        # Chunk size 2000 is a good balance for memory vs DB trips
        for ph in base_qs.iterator(chunk_size=2000):
            history = ph.rows
            if not history:
                continue

            hood = ph.neighborhood_code
            
            for rec in history:
                # Type check is faster than try/except
                if not isinstance(rec, dict):
                    continue

                year_raw = rec.get("VALUE YEAR") or rec.get("TAX YEAR")
                if not year_raw:
                    continue
                
                try:
                    value_year = int(str(year_raw))
                except ValueError:
                    continue

                # Direct dict access is slightly faster than .get() for known keys
                # We use set default implicitly via defaultdict above
                bucket = buckets[(hood, value_year)]
                hood_years[hood].add(value_year)

                lm = parse_money_fast(rec.get("LAND MARKET"))
                if lm is not None: bucket.land.append(lm)

                bld = parse_money_fast(rec.get("BUILDING"))
                if bld is not None: bucket.building.append(bld)

                tot = parse_money_fast(rec.get("MARKET TOTAL"))
                if tot is not None: bucket.total.append(tot)

                tax = parse_money_fast(rec.get("TAX"))
                if tax is not None: bucket.tax.append(tax)

            processed += 1
            if processed % 10000 == 0:
                self.stdout.write(f"Processed {processed} rows...")

        self.stdout.write(f"Aggregating {len(buckets)} data buckets using NumPy...")

        # ------------------------------------------------------------------
        # 3. Calculation (The Reduce Phase with NumPy)
        # ------------------------------------------------------------------
        trend_rows = []

        # Helper for YoY calculation
        def calc_yoy(curr, prev):
            if curr is None or prev is None or prev == 0:
                return None
            return (curr - prev) * 100.0 / prev

        for hood, year_set in hood_years.items():
            sorted_years = sorted(year_set)
            
            prev_stats = {'land': None, 'bld': None, 'total': None, 'tax': None}
            yoy_total_list = []
            per_year_data = []

            for year in sorted_years:
                bucket = buckets.get((hood, year))
                
                # --- NUMPY OPTIMIZATION START ---
                # We convert to array only if data exists.
                # np.median returns float64, so we cast to int for the DB.
                
                med_land = int(np.median(bucket.land)) if bucket.land else None
                med_bld = int(np.median(bucket.building)) if bucket.building else None
                med_total = int(np.median(bucket.total)) if bucket.total else None
                med_tax = int(np.median(bucket.tax)) if bucket.tax else None
                # --- NUMPY OPTIMIZATION END ---

                yoy_total = calc_yoy(med_total, prev_stats['total'])
                
                if yoy_total is not None:
                    yoy_total_list.append(yoy_total)

                per_year_data.append({
                    "hood": hood,
                    "year": year,
                    "med_land": med_land,
                    "med_bld": med_bld,
                    "med_total": med_total,
                    "med_tax": med_tax,
                    "yoy_land": calc_yoy(med_land, prev_stats['land']),
                    "yoy_bld": calc_yoy(med_bld, prev_stats['bld']),
                    "yoy_total": yoy_total,
                    "yoy_tax": calc_yoy(med_tax, prev_stats['tax']),
                })

                prev_stats = {
                    'land': med_land, 'bld': med_bld, 
                    'total': med_total, 'tax': med_tax
                }

            # --- NUMPY STD DEVIATION ---
            if len(yoy_total_list) >= 2:
                # np.std is much faster than statistics.pstdev
                sigma = float(np.std(yoy_total_list)) 
                stability_score = max(0.0, 100.0 - sigma * 1.5)
            else:
                stability_score = None

            for d in per_year_data:
                yt = d["yoy_total"]
                if yt is None:
                    flag = ""
                elif yt > 8:
                    flag = "boom"
                elif yt < -8:
                    flag = "bust"
                else:
                    flag = "steady"

                trend_rows.append(NeighborhoodTrend(
                    hood_id=d["hood"],
                    value_year=d["year"],
                    median_land_market=d["med_land"],
                    median_building=d["med_bld"],
                    median_market_total=d["med_total"],
                    median_tax_amount=d["med_tax"],
                    yoy_change_land=d["yoy_land"],
                    yoy_change_building=d["yoy_bld"],
                    yoy_change_total=d["yoy_total"],
                    yoy_change_tax=d["yoy_tax"],
                    stability_score=stability_score,
                    boom_bust_flag=flag,
                ))

        self.stdout.write(f"Prepared {len(trend_rows)} trend rows.")

        # ------------------------------------------------------------------
        # 4. Bulk Write
        # ------------------------------------------------------------------
        with transaction.atomic():
            if hood_prefix:
                NeighborhoodTrend.objects.filter(hood_id__startswith=hood_prefix).delete()
            else:
                q = models.Q()
                for p in target_prefixes:
                    q |= models.Q(hood_id__startswith=p)
                NeighborhoodTrend.objects.filter(q).delete()

            # Batch size 2000 is usually optimal for Postgres/MySQL
            NeighborhoodTrend.objects.bulk_create(trend_rows, batch_size=2000)

        self.stdout.write(self.style.SUCCESS(f"Done. Created {len(trend_rows)} NeighborhoodTrend records."))