from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from openskagit.models import Assessor, Improvements

# Main-area type prefixes
MAIN_AREA_PREFIXES = ("MA", "MW", "SW", "MH", "MF", "DW")

QUALITY_MAP = {
    "MSE": 6, "MSVG": 5, "MSVG+": 5, "MSG+": 4, "MSG": 4,
    "MSA": 3, "MSA+": 3, "MSF": 2, "MSL": 1,
}

CONDITION_MAP = {
    "E": 6, "VG": 5, "G": 4, "A": 3, "F": 2, "P": 1, "L": 0,
    "U": 3,
}


def _compute_quality_score_from_dicts(rows):
    """
    Compute average quality score from list of improvement dicts.
    """
    scores = []
    for row in rows:
        class_code = (row["improvement_detail_class_code"] or "").strip().upper()
        score = QUALITY_MAP.get(class_code)
        if score is not None:
            scores.append(score)

    if not scores:
        return None

    return sum(scores) / len(scores)


def _compute_condition_from_dicts(rows):
    """
    Compute best condition_code + condition_score from list of improvement dicts.
    """
    best_code = None
    best_score = None

    for row in rows:
        raw_code = (row["condition_code"] or "").strip().upper()
        if not raw_code:
            continue

        score = CONDITION_MAP.get(raw_code)
        if score is None:
            continue

        if best_score is None or score > best_score:
            best_score = score
            best_code = raw_code

    if best_code is None:
        return "U", CONDITION_MAP["U"]

    return best_code, best_score


class Command(BaseCommand):
    help = "Backfill Assessor quality/condition using in-memory aggregation and bulk updates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only update rows where quality_score or condition_score is NULL.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="How many Assessor rows to process per bulk update.",
        )

    def handle(self, *args, **options):
        only_missing = options["only_missing"]
        batch_size = options["batch_size"]

        # --- STEP 1: Build Improvements Lookup (Eliminates N+1 Reads) ---
        self.stdout.write("Fetching Improvements data...")

        # We fetch ONLY the columns we need to save memory.
        # We fetch ALL improvements and filter in Python to ensure the .strip() logic
        # matches your original code exactly (SQL LIKE can be tricky with whitespace).
        imps_iterator = Improvements.objects.all().values(
            "roll_id",
            "parcel_number",
            "improvement_detail_type_code",
            "improvement_detail_class_code",
            "condition_code",
        ).iterator(chunk_size=5000)

        # Group improvements by (roll_id, parcel_number)
        parcel_groups = defaultdict(list)
        
        count_imps = 0
        for row in imps_iterator:
            # Filter: Is this a main area?
            type_code = (row["improvement_detail_type_code"] or "").strip().upper()
            if not type_code.startswith(MAIN_AREA_PREFIXES):
                continue

            # Key generation
            r_id = row["roll_id"]
            p_num = (row["parcel_number"] or "").strip()
            if not r_id or not p_num:
                continue

            parcel_groups[(r_id, p_num)].append(row)
            count_imps += 1

        self.stdout.write(f"Aggregated {count_imps} relevant improvement records into {len(parcel_groups)} parcels.")

        # Pre-calculate the final scores for every parcel in our lookup
        # lookup format: {(roll, parcel): (quality_score, cond_code, cond_score)}
        parcel_lookup = {}
        for key, rows in parcel_groups.items():
            q_score = _compute_quality_score_from_dicts(rows)
            c_code, c_score = _compute_condition_from_dicts(rows)
            parcel_lookup[key] = (q_score, c_code, c_score)
        
        # Free up memory
        del parcel_groups

        # --- STEP 2: Prepare Assessor QuerySet ---
        qs = Assessor.objects.all().order_by("id")
        if only_missing:
            qs = qs.filter(quality_score__isnull=True) | qs.filter(condition_score__isnull=True)

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No Assessor rows to process."))
            return

        self.stdout.write(f"Processing {total} Assessor rows...")

        # --- STEP 3: Bulk Update Loop ---
        update_batch = []
        processed = 0
        updated_total = 0

        for assessor in qs.iterator(chunk_size=2000):
            processed += 1
            
            key = (assessor.roll_id, (assessor.parcel_number or "").strip())
            data = parcel_lookup.get(key)

            if not data:
                continue

            new_q_score, new_c_code, new_c_score = data

            # Detect changes
            changed = False

            # Quality Score Check
            if new_q_score is not None:
                # Use small epsilon for float comparison
                current_q = assessor.quality_score
                if current_q is None or abs(current_q - new_q_score) > 1e-4:
                    assessor.quality_score = new_q_score
                    changed = True
            
            # Condition Code Check
            if assessor.condition_code != new_c_code:
                assessor.condition_code = new_c_code
                changed = True

            # Condition Score Check
            if assessor.condition_score != new_c_score:
                assessor.condition_score = new_c_score
                changed = True

            # Only add to batch if something actually changed
            if changed:
                update_batch.append(assessor)

            # Execute Bulk Update
            if len(update_batch) >= batch_size:
                Assessor.objects.bulk_update(
                    update_batch, 
                    ["quality_score", "condition_code", "condition_score"]
                )
                updated_total += len(update_batch)
                self.stdout.write(f"Processed {processed}/{total} | Updated {updated_total}...")
                update_batch = []

        # --- STEP 4: Flush Remainder ---
        if update_batch:
            Assessor.objects.bulk_update(
                update_batch, 
                ["quality_score", "condition_code", "condition_score"]
            )
            updated_total += len(update_batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {processed} rows. Updated {updated_total} Assessor rows."
            )
        )