import sys
import numpy as np
from collections import defaultdict
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand
from django.db import transaction, models
from openskagit.models import ParcelHistory, NeighborhoodTrend, Assessor

# -------------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------------

DEFAULT_PREFIXES = (
    "20MV", "21MV", "22MV", "23MV",
    "20LC", "21LC", "22LC", "23LC",
    "20B", "21B", "22B", "23B", "26B", "27B",
    "20A", "21A", "22A", "23A", "20FID", "22FID", "20GUEM", "22GUEM",
    "20SW", "21SW", "22SW", "23SW",
    "20CC", "22CC", "10CC",
)

REMOVE_MONEY_CHARS = str.maketrans("", "", "$,")

# -------------------------------------------------------------------------
# UTILS
# -------------------------------------------------------------------------

def parse_money_fast(raw: object) -> int:
    """Fastest way to turn '$4,900.00' or '$.00' into integer 4900."""
    if raw is None: return 0
    if isinstance(raw, (int, float)): return int(raw + 0.5)
    
    s = str(raw)
    if not s or s == "$.00" or s == "$0" or s == "0": return 0
    
    clean_s = s.translate(REMOVE_MONEY_CHARS)
    if not clean_s or clean_s == ".00": return 0

    try:
        return int(float(clean_s) + 0.5)
    except ValueError:
        return 0

class YearBucket:
    __slots__ = ("land", "building", "total", "tax")
    def __init__(self):
        self.land = []
        self.building = []
        self.total = []
        self.tax = []

# -------------------------------------------------------------------------
# COMMAND
# -------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Build Trends combining Assessor (Hood Code) + ParcelHistory (Values)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hood", 
            help="Optional: Only process a specific hood prefix (e.g. '20MV')"
        )

    def handle(self, *args, **options):
        hood_arg = options.get("hood")
        
        # Determine which prefixes we are filtering for
        if hood_arg:
            target_prefixes = (hood_arg,)
            self.stdout.write(self.style.MIGRATE_HEADING(f"1. Building Lookup Map (Filtered for '{hood_arg}')..."))
        else:
            target_prefixes = DEFAULT_PREFIXES
            self.stdout.write(self.style.MIGRATE_HEADING("1. Building Lookup Map (All Targets)..."))

        # ------------------------------------------------------------------
        # STEP 1: Build the "Parcel -> Neighborhood" Map
        # ------------------------------------------------------------------
        # We perform the filtering here. If --hood is provided, the Map
        # will ONLY contain parcels for that hood.
        # Later, when we scan ParcelHistory, any parcel NOT in this map is ignored.
        
        assessor_qs = Assessor.objects.filter(
            neighborhood_code__isnull=False
        ).exclude(neighborhood_code="")

        # Apply filter efficiently at DB level
        if hood_arg:
             assessor_qs = assessor_qs.filter(neighborhood_code__startswith=hood_arg)
        else:
            # Build OR query for default prefixes
            q = models.Q()
            for p in target_prefixes:
                q |= models.Q(neighborhood_code__startswith=p)
            assessor_qs = assessor_qs.filter(q)

        assessor_qs = assessor_qs.values_list('parcel_number', 'neighborhood_code')

        parcel_map = {}
        
        # Load the map
        for p_num, hood_code in assessor_qs.iterator(chunk_size=10000):
            p_num = str(p_num).strip()
            parcel_map[p_num] = str(hood_code).strip()

        map_size = len(parcel_map)
        self.stdout.write(f"Map Built. Loaded {map_size} parcels into memory.")

        if map_size == 0:
            self.stdout.write(self.style.WARNING("No parcels found in Assessor table matching your criteria."))
            return

        # ------------------------------------------------------------------
        # STEP 2: Stream ParcelHistory and Join in Memory
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("2. Scanning ParcelHistory..."))
        
        # We rely on the Map to do the filtering. We just stream history.
        history_qs = ParcelHistory.objects.exclude(rows__isnull=True).only("parcel_number", "rows")

        buckets: Dict[Tuple[str, int], YearBucket] = defaultdict(YearBucket)
        hood_years: defaultdict[str, set] = defaultdict(set)
        
        processed = 0
        matched = 0

        # Scan
        for ph in history_qs.iterator(chunk_size=2000):
            processed += 1
            if processed % 10000 == 0:
                self.stdout.write(f"Scanned {processed} history rows (Matched {matched})...")

            # LOOKUP: O(1) Check
            p_num = str(ph.parcel_number).strip()
            hood_id = parcel_map.get(p_num)

            # If hood_id is None, it means either:
            # 1. The parcel isn't in our target prefixes
            # 2. Or (if --hood used) it's not in the specific hood we requested.
            if not hood_id:
                continue 

            matched += 1
            history = ph.rows
            
            if not isinstance(history, list): continue

            for rec in history:
                if not isinstance(rec, dict): continue

                year_raw = rec.get("VALUE YEAR") or rec.get("TAX YEAR")
                if not year_raw: continue
                
                try:
                    year = int(str(year_raw))
                except ValueError: continue

                if year < 1990: continue

                # Add to Bucket
                key = (hood_id, year)
                bucket = buckets[key]
                hood_years[hood_id].add(year)

                lm = parse_money_fast(rec.get("LAND MARKET"))
                if lm: bucket.land.append(lm)

                bld = parse_money_fast(rec.get("BUILDING"))
                if bld: bucket.building.append(bld)

                tot = parse_money_fast(rec.get("MARKET TOTAL"))
                if tot: bucket.total.append(tot)

                tax = parse_money_fast(rec.get("TAX"))
                if tax: bucket.tax.append(tax)

        self.stdout.write(f"Scan complete. Found data for {len(hood_years)} neighborhoods.")

        # ------------------------------------------------------------------
        # STEP 3: NumPy Calculation (Reduce Phase)
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("3. Calculating Trends (NumPy)..."))
        
        trend_rows = []

        def get_yoy(curr, prev):
            if curr is None or prev is None or prev == 0: return None
            return round((curr - prev) * 100.0 / prev, 2)

        for hood, years in hood_years.items():
            sorted_years = sorted(years)
            prev_stats = {'total': None, 'land': None, 'bld': None, 'tax': None}
            yoy_history = []
            temp_rows = []

            for year in sorted_years:
                bucket = buckets.get((hood, year))
                
                # NumPy Medians
                med_total = int(np.median(bucket.total)) if bucket.total else 0
                med_land = int(np.median(bucket.land)) if bucket.land else 0
                med_bld = int(np.median(bucket.building)) if bucket.building else 0
                med_tax = int(np.median(bucket.tax)) if bucket.tax else 0

                yoy_total = get_yoy(med_total, prev_stats['total'])
                
                if yoy_total is not None:
                    yoy_history.append(yoy_total)

                row_data = {
                    "hood_id": hood,
                    "value_year": year,
                    "med_total": med_total,
                    "med_land": med_land,
                    "med_bld": med_bld,
                    "med_tax": med_tax,
                    "yoy_total": yoy_total,
                    "yoy_land": get_yoy(med_land, prev_stats['land']),
                    "yoy_bld": get_yoy(med_bld, prev_stats['bld']),
                    "yoy_tax": get_yoy(med_tax, prev_stats['tax']),
                }
                temp_rows.append(row_data)

                prev_stats = {'total': med_total, 'land': med_land, 'bld': med_bld, 'tax': med_tax}

            # Stability Score
            stability_score = None
            if len(yoy_history) >= 2:
                sigma = float(np.std(yoy_history))
                stability_score = max(0.0, 100.0 - (sigma * 1.5))

            # Finalize
            for d in temp_rows:
                yt = d['yoy_total']
                if yt is None: flag = "steady"
                elif yt > 10: flag = "boom"
                elif yt < -10: flag = "bust"
                else: flag = "steady"

                trend_rows.append(NeighborhoodTrend(
                    hood_id=d['hood_id'],
                    value_year=d['value_year'],
                    median_market_total=d['med_total'],
                    median_land_market=d['med_land'],
                    median_building=d['med_bld'],
                    median_tax_amount=d['med_tax'],
                    yoy_change_total=d['yoy_total'],
                    yoy_change_land=d['yoy_land'],
                    yoy_change_building=d['yoy_bld'],
                    yoy_change_tax=d['yoy_tax'],
                    stability_score=stability_score,
                    boom_bust_flag=flag
                ))

        # ------------------------------------------------------------------
        # STEP 4: Database Write
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING(f"4. Writing {len(trend_rows)} rows to DB..."))
        
        with transaction.atomic():
            # Delete logic depends on whether we filtered or not
            if hood_arg:
                # If we only ran 20MV, only delete 20MV trends
                NeighborhoodTrend.objects.filter(hood_id__startswith=hood_arg).delete()
            else:
                # Otherwise clear all targets
                q = models.Q()
                for p in target_prefixes:
                    q |= models.Q(hood_id__startswith=p)
                NeighborhoodTrend.objects.filter(q).delete()

            NeighborhoodTrend.objects.bulk_create(trend_rows, batch_size=2000)

        self.stdout.write(self.style.SUCCESS("Success! Neighborhood Trends Rebuilt."))