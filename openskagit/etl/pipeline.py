from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Set, Tuple

from django.db import transaction

from openskagit.improvement_utils import improvement_category
from openskagit.models import Assessor, AssessmentRoll, Improvements

# Type/category normalization
MAIN_STRUCTURE_PREFIXES = ("MA", "MW", "SW", "MH", "MF", "DW", "UF", "PM")
GARAGE_PREFIXES = ("AG", "DG", "GBI", "GAR", "CARP", "LOFT")
DECK_PREFIXES = ("DECK", "CWP", "WDK")
PORCH_PREFIXES = ("POR", "PCH", "ENP", "SUN")
BASEMENT_PREFIXES = ("BM",)
FINISHED_BASEMENT_PREFIXES = ("BMF", "BMG")
SHOP_PREFIXES = ("SHOP", "MPS", "GPB")
SHED_PREFIXES = ("SH", "SHD", "MSHD", "BU")
POOL_PREFIXES = ("POOL", "SPL", "SPA", "HOTTUB")

EXACT_CODE_CATEGORY: Dict[str, str] = {
    "ARNA": "outbuilding",  # horse arenas / indoor riding areas
    "BMG": "basement",  # basement in good condition (treated as finished)
    "BML": "basement",  # basement in low condition
    "BMU": "unfinished_basement",  # unfinished basement
    "BSMT": "basement",
    "C-S": "outbuilding",
    "CP": "porch",
    "DG1.5": "garage",
    "DG2": "garage",
    "DGAR": "garage",
    "DOCK": "outbuilding",
    "GREENH": "outbuilding",
    "GRNH": "outbuilding",
    "GARFIN": "main_structure",  # finished garage living area
    "LB-LOFT": "outbuilding",
    "LOFT": "main_structure",
    "LFT": "outbuilding",
    "OFP": "outbuilding",
    "UF1.5F": "main_structure",
    "UF1.5U": "main_structure",
    "UF2": "main_structure",
    "UF2.5F": "main_structure",
    "UF2.5U": "main_structure",
    "UF3": "main_structure",
    "MA":"main_structure",
    "MA1.5": "main_structure",
    "MA2": "main_structure",
    "MA2.5": "main_structure",
    "MA3": "main_structure",
}

# Quality/condition mappings (mirrors backfill_quality_condition.py)
QUALITY_MAP = {
    "MSE": 6,
    "MSVG": 5,
    "MSVG+": 5,
    "MSG+": 4,
    "MSG": 4,
    "MSA": 3,
    "MSA+": 3,
    "MSF": 2,
    "MSL": 1,
}

CONDITION_MAP = {
    "E": 6,
    "VG": 5,
    "G": 4,
    "A": 3,
    "F": 2,
    "P": 1,
    "L": 0,
    "U": 3,
}

# Bathroom token mapping (plumbing codes)
BATH_TOKEN_VALUES: Dict[str, float] = {
    "MB": 1.0,
    "FB": 1.0,
    "QB": 0.75,
    "HB": 0.5,
    "BTH": 1.0,
    "FULL": 1.0,
    "HALF": 0.5,
    "QTR": 0.25,
}

PAREN_CODE_RE = re.compile(r"\(([^)]+)\)\s*(.*)")

ASSESSOR_UPDATE_FIELDS = [
    "neighborhood_code",
    "neighborhood_code_description",
    "neighborhood_id",
    "land_use_code",
    "land_use_description",
    "quality_score",
    "condition_code",
    "condition_score",
    "bathrooms",
    "full_bathrooms",
    "half_bathrooms",
    "total_outbuilding_area",
    "total_deck_area",
    "total_porch_area",
    "total_garage_area",
    "total_basement_area",
    "calculated_square_footage",
    "total_improvement_value",
    "number_of_sheds",
    "number_of_shops",
    "number_of_outbuildings",
    "number_of_fireplaces",
    "has_pool",
    "has_shop",
    "has_deck",
    "has_finished_basement",
    "improvement_year_built",
    "age",
    "age_sq",
    "age_bucket",
    "renovation_age",
]

CODE_CLEAN_FIELDS = [
    "neighborhood_code",
    "neighborhood_code_description",
    "neighborhood_id",
    "land_use_code",
    "land_use_description",
]

AGE_FIELDS = [
    "improvement_year_built",
    "age",
    "age_sq",
    "age_bucket",
    "renovation_age",
]


TARGETABLE_FIELDS: Set[str] = frozenset(
    {
        "bathrooms",
        "full_bathrooms",
        "half_bathrooms",
        "total_outbuilding_area",
        "total_deck_area",
        "total_porch_area",
        "total_garage_area",
        "total_basement_area",
        "total_improvement_value",
        "number_of_sheds",
        "number_of_shops",
        "number_of_outbuildings",
        "number_of_fireplaces",
        "has_pool",
        "has_shop",
        "has_deck",
        "has_finished_basement",
        "quality_score",
        "condition_code",
        "condition_score",
        "improvement_year_built",
        "age",
        "age_sq",
        "age_bucket",
        "renovation_age",
    }
)


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().upper()


def _clean_parcel_number(parcel_number: Optional[str]) -> Optional[str]:
    pn = (parcel_number or "").strip()
    return pn or None


def _coerce_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _coerce_int(value: object) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _split_code_and_description(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse values like "(110) UGA" into ("110", "UGA").
    """
    if not raw:
        return None, None
    text = str(raw).strip()
    match = PAREN_CODE_RE.match(text)
    if match:
        code = match.group(1).strip().upper()
        desc = match.group(2).strip().title() or None
        return code or None, desc
    return text.upper(), None


def _clean_type_code(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return "".join(str(raw).strip().upper().split())


def _numeric_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.findall(r"\d+", value)
    if not digits:
        return None
    return "".join(digits)


def _bucket_age(age: float) -> str:
    if age <= 10:
        return "0-10"
    if age <= 30:
        return "10-30"
    if age <= 60:
        return "30-60"
    return "60+"


def _categorize_improvement(type_code: str) -> str:
    override = EXACT_CODE_CATEGORY.get(type_code)
    if override:
        return override

    for prefix in GARAGE_PREFIXES:
        if type_code.startswith(prefix):
            return "garage"
    for prefix in DECK_PREFIXES:
        if type_code.startswith(prefix):
            return "deck"
    for prefix in PORCH_PREFIXES:
        if type_code.startswith(prefix):
            return "porch"
    for prefix in BASEMENT_PREFIXES:
        if type_code.startswith(prefix):
            return "basement"
    for prefix in SHOP_PREFIXES:
        if type_code.startswith(prefix):
            return "shop"
    for prefix in SHED_PREFIXES:
        if type_code.startswith(prefix):
            return "shed"
    for prefix in POOL_PREFIXES:
        if type_code.startswith(prefix):
            return "pool"

    fallback = improvement_category(type_code)
    if fallback == "garage":
        return "garage"
    if fallback == "outbuilding":
        return "outbuilding"
    if fallback == "home":
        return "main_structure"
    return "misc"


def _is_main_structure(type_code: str) -> bool:
    return any(type_code.startswith(prefix) for prefix in MAIN_STRUCTURE_PREFIXES)


def _is_finished_basement(type_code: str) -> bool:
    return any(type_code.startswith(prefix) for prefix in FINISHED_BASEMENT_PREFIXES)


def _normalize_multiplier(multiplier: str, token_type: str) -> int:
    """
    Normalize digit strings (e.g., '33' → 3 when they are repeating) before counting.
    """
    if not multiplier:
        return 1
    if len(multiplier) == 1:
        if token_type == "QB":
            return 1
        try:
            return int(multiplier)
        except ValueError:
            return 1
    if len(set(multiplier)) == 1:
        return int(multiplier[0])
    try:
        return int(multiplier)
    except ValueError:
        return 1


def _parse_bath_tokens(plumbing_code: Optional[str]) -> Tuple[int, int, int]:
    """
    Returns (full, half, quarter) counts parsed from a plumbing code string.
    """
    if not plumbing_code:
        return 0, 0, 0

    full = 0
    half = 0
    quarter = 0
    tokens = re.split(r"[;,]+|\s+", plumbing_code)

    for token in tokens:
        key = token.strip().upper()
        if not key:
            continue
        multiplier_match = re.match(r"(?P<count>\d+)(?P<token>[A-Z]+)", key)
        if multiplier_match:
            token_type = multiplier_match.group("token")
            count = _normalize_multiplier(multiplier_match.group("count"), token_type)
            value = BATH_TOKEN_VALUES.get(token_type)
            if value is None:
                continue
            if math.isclose(value, 1.0):
                full += count
            elif math.isclose(value, 0.5):
                half += count
            elif math.isclose(value, 0.75):
                quarter += count
            continue

        value = BATH_TOKEN_VALUES.get(key)
        if value is None:
            continue
        if math.isclose(value, 1.0):
            full += 1
        elif math.isclose(value, 0.5):
            half += 1
        elif math.isclose(value, 0.75):
            quarter += 1

    return full, half, quarter


@dataclass
class ParcelAccumulator:
    parcel_number: str
    total_outbuilding_area: float = 0.0
    total_deck_area: float = 0.0
    total_porch_area: float = 0.0
    total_garage_area: float = 0.0
    total_basement_area: float = 0.0
    total_main_structure_area: float = 0.0
    total_improvement_value: int = 0
    number_of_sheds: int = 0
    number_of_shops: int = 0
    number_of_outbuildings: int = 0
    number_of_fireplaces: int = 0
    has_pool: bool = False
    has_shop: bool = False
    has_deck: bool = False
    has_finished_basement: bool = False
    saw_basement: bool = False
    bath_full: int = 0
    bath_half: int = 0
    bath_quarter: int = 0
    bath_evidence: bool = False
    quality_weighted_sum: float = 0.0
    quality_weight_total: float = 0.0
    condition_best: Optional[Tuple[int, str, int]] = None
    best_effective_year: Optional[int] = None
    best_effective_score: float = -1.0
    best_actual_year: Optional[int] = None
    best_actual_score: float = -1.0
    best_new_construction_year: Optional[int] = None
    value_seen: bool = False

    def add_row(self, row: Dict[str, object]) -> None:
        type_code = _clean_type_code(row.get("improvement_detail_type_code"))
        if not type_code:
            return

        area = _coerce_float(row.get("calculated_area")) or _coerce_float(row.get("total_living_area")) or 0.0
        value = _coerce_int(row.get("improvement_detail_value"))

        category = _categorize_improvement(type_code)

        if category == "main_structure":
            self.total_main_structure_area += area

        if category in {"shop", "shed", "outbuilding"}:
            self.total_outbuilding_area += area
            self.number_of_outbuildings += 1
            if category == "shop":
                self.number_of_shops += 1
                self.has_shop = True
            if category == "shed":
                self.number_of_sheds += 1

        if category == "garage":
            self.total_garage_area += area
            self.number_of_outbuildings += 1

        if category == "deck":
            self.total_deck_area += area
            self.has_deck = self.has_deck or area > 0

        if category == "porch":
            self.total_porch_area += area

        if category == "basement":
            self.total_basement_area += area
            self.saw_basement = True
            if _is_finished_basement(type_code):
                self.has_finished_basement = True

        if category == "pool":
            self.has_pool = True

        if value is not None:
            self.value_seen = True
            self.total_improvement_value += int(value)

        self._process_bathrooms(row.get("plumbing_code"))
        self._process_quality_condition(type_code, row.get("improvement_detail_class_code"), row.get("condition_code"))
        self._process_years(value, row)
        self._process_fireplace(row.get("fireplace"))

    def _process_fireplace(self, raw: object) -> None:
        count = _coerce_int(raw)
        if count is None:
            return
        self.number_of_fireplaces += count

    def _process_bathrooms(self, plumbing_code: Optional[str]) -> None:
        full, half, quarter = _parse_bath_tokens(plumbing_code)
        if full or half or quarter:
            self.bath_evidence = True
        self.bath_full += full
        self.bath_half += half
        self.bath_quarter += quarter

    def _process_quality_condition(self, type_code: str, class_code: Optional[str], condition_code: Optional[str]) -> None:
        weight = 2 if _is_main_structure(type_code) else 1

        quality_score = QUALITY_MAP.get(_norm(class_code))
        if quality_score is not None:
            self.quality_weighted_sum += quality_score * weight
            self.quality_weight_total += weight

        cond_code_norm = _norm(condition_code)
        cond_score = CONDITION_MAP.get(cond_code_norm)
        if cond_score is not None:
            if self.condition_best is None or cond_score > self.condition_best[0] or (
                cond_score == self.condition_best[0] and weight > self.condition_best[2]
            ):
                self.condition_best = (cond_score, cond_code_norm, weight)

    def _process_years(self, value: Optional[int], row: Dict[str, object]) -> None:
        value_score = float(value or 0)
        effective_year = _coerce_int(row.get("effective_year_built"))
        actual_year = _coerce_int(row.get("actual_year_built"))
        new_construction_year = _coerce_int(row.get("new_construction_year"))

        if effective_year is not None:
            if self.best_effective_year is None or value_score > self.best_effective_score or (
                math.isclose(value_score, self.best_effective_score) and effective_year > self.best_effective_year
            ):
                self.best_effective_year = effective_year
                self.best_effective_score = value_score

        if actual_year is not None and self.best_effective_year is None:
            if self.best_actual_year is None or value_score > self.best_actual_score or (
                math.isclose(value_score, self.best_actual_score) and actual_year > self.best_actual_year
            ):
                self.best_actual_year = actual_year
                self.best_actual_score = value_score

        if new_construction_year is not None:
            if self.best_new_construction_year is None or new_construction_year > self.best_new_construction_year:
                self.best_new_construction_year = new_construction_year

    def quality_score(self) -> Optional[float]:
        if self.quality_weight_total <= 0:
            return None
        return self.quality_weighted_sum / self.quality_weight_total

    def condition(self) -> Optional[Tuple[str, int]]:
        if not self.condition_best:
            return None
        score, code, _ = self.condition_best
        return code, score

    def apply_to_assessor(self, assessor: Assessor, roll_year: int) -> bool:
        changed = False

        # Areas and counts
        for field, value in [
            ("total_outbuilding_area", self.total_outbuilding_area),
            ("total_deck_area", self.total_deck_area),
            ("total_porch_area", self.total_porch_area),
            ("total_garage_area", self.total_garage_area),
            ("total_basement_area", self.total_basement_area),
            ("number_of_sheds", self.number_of_sheds),
            ("number_of_shops", self.number_of_shops),
            ("number_of_outbuildings", self.number_of_outbuildings),
            ("number_of_fireplaces", self.number_of_fireplaces),
        ]:
            if getattr(assessor, field) != value:
                setattr(assessor, field, value)
                changed = True

        calculated_sqft = self.total_main_structure_area + self.total_basement_area
        if assessor.calculated_square_footage != calculated_sqft:
            assessor.calculated_square_footage = calculated_sqft
            changed = True

        if self.value_seen and assessor.total_improvement_value != self.total_improvement_value:
            assessor.total_improvement_value = self.total_improvement_value
            changed = True

        finished_basement_value: Optional[bool] = None
        if self.has_finished_basement:
            finished_basement_value = True
        elif self.saw_basement:
            finished_basement_value = False

        for field, value in [
            ("has_pool", bool(self.has_pool)),
            ("has_shop", bool(self.has_shop)),
            ("has_deck", bool(self.has_deck)),
        ]:
            if getattr(assessor, field) != value:
                setattr(assessor, field, value)
                changed = True

        if finished_basement_value is not None and assessor.has_finished_basement != finished_basement_value:
            assessor.has_finished_basement = finished_basement_value
            changed = True

        # Bathrooms
        if self.bath_evidence:
            total_bathrooms = self.bath_full + (self.bath_half * 0.5) + (self.bath_quarter * 0.25)
            if assessor.bathrooms != total_bathrooms:
                assessor.bathrooms = total_bathrooms
                changed = True
            if assessor.full_bathrooms != self.bath_full:
                assessor.full_bathrooms = self.bath_full
                changed = True
            if assessor.half_bathrooms != self.bath_half:
                assessor.half_bathrooms = self.bath_half
                changed = True

        # Quality/condition
        q_score = self.quality_score()
        if q_score is not None and assessor.quality_score != q_score:
            assessor.quality_score = q_score
            changed = True

        cond = self.condition()
        if cond:
            code, score = cond
            if assessor.condition_code != code:
                assessor.condition_code = code
                changed = True
            if assessor.condition_score != score:
                assessor.condition_score = score
                changed = True

        # Age features
        final_year_raw = (
            self.best_effective_year
            or self.best_actual_year
            or assessor.eff_year_built
            or assessor.year_built
        )
        final_year = _coerce_int(final_year_raw)
        if final_year:
            if assessor.improvement_year_built != final_year:
                assessor.improvement_year_built = final_year
                changed = True
            age = float(max(roll_year - final_year, 0))
            age_sq = age * age
            age_bucket = _bucket_age(age)
            if assessor.age != age:
                assessor.age = age
                changed = True
            if assessor.age_sq != age_sq:
                assessor.age_sq = age_sq
                changed = True
            if assessor.age_bucket != age_bucket:
                assessor.age_bucket = age_bucket
                changed = True
            if self.best_new_construction_year:
                renovation_age = float(max(roll_year - self.best_new_construction_year, 0))
                if assessor.renovation_age != renovation_age:
                    assessor.renovation_age = renovation_age
                    changed = True

        return changed


def clean_assessor_codes(assessor: Assessor) -> bool:
    changed = False

    hood_code, hood_desc = _split_code_and_description(assessor.neighborhood_code)
    hood_id = _numeric_token(hood_code) or _numeric_token(assessor.neighborhood_code)

    if hood_code and assessor.neighborhood_code != hood_code:
        assessor.neighborhood_code = hood_code
        changed = True
    if hood_desc and assessor.neighborhood_code_description != hood_desc:
        assessor.neighborhood_code_description = hood_desc
        changed = True
    if hood_id and assessor.neighborhood_id != hood_id:
        assessor.neighborhood_id = hood_id
        changed = True

    land_code, land_desc = _split_code_and_description(assessor.land_use_code)

    if land_code and assessor.land_use_code != land_code:
        assessor.land_use_code = land_code
        changed = True
    if land_desc and assessor.land_use_description != land_desc:
        assessor.land_use_description = land_desc
        changed = True

    return changed


def _apply_age_features(assessor: Assessor, roll_year: int) -> bool:
    final_year = _coerce_int(assessor.eff_year_built or assessor.year_built)
    if not final_year:
        return False

    changed = False
    if assessor.improvement_year_built != final_year:
        assessor.improvement_year_built = final_year
        changed = True

    age = float(max(roll_year - final_year, 0))
    age_sq = age * age
    age_bucket = _bucket_age(age)

    if assessor.age != age:
        assessor.age = age
        changed = True
    if assessor.age_sq != age_sq:
        assessor.age_sq = age_sq
        changed = True
    if assessor.age_bucket != age_bucket:
        assessor.age_bucket = age_bucket
        changed = True

    if assessor.renovation_age is None and assessor.eff_year_built is not None and assessor.eff_year_built > final_year:
        renovation_age = float(max(roll_year - assessor.eff_year_built, 0))
        assessor.renovation_age = renovation_age
        changed = True

    return changed


def _process_code_cleaning_batch(
    qs,
    *,
    batch_size: int,
    dry_run: bool,
) -> int:
    updated_batch: list[Assessor] = []
    updated_total = 0

    def _flush():
        nonlocal updated_total
        if not updated_batch:
            return
        if not dry_run:
            Assessor.objects.bulk_update(updated_batch, CODE_CLEAN_FIELDS, batch_size=batch_size)
        updated_total += len(updated_batch)
        updated_batch.clear()

    for assessor in qs.iterator(chunk_size=batch_size):
        if clean_assessor_codes(assessor):
            updated_batch.append(assessor)
            if len(updated_batch) >= batch_size:
                _flush()

    _flush()
    return updated_total


def _process_age_batch(
    qs,
    *,
    roll_year: int,
    batch_size: int,
    dry_run: bool,
) -> int:
    updated_batch: list[Assessor] = []
    updated_total = 0

    def _flush():
        nonlocal updated_total
        if not updated_batch:
            return
        if not dry_run:
            Assessor.objects.bulk_update(updated_batch, AGE_FIELDS, batch_size=batch_size)
        updated_total += len(updated_batch)
        updated_batch.clear()

    for assessor in qs.iterator(chunk_size=batch_size):
        if _apply_age_features(assessor, roll_year):
            updated_batch.append(assessor)
            if len(updated_batch) >= batch_size:
                _flush()

    _flush()
    return updated_total


def _aggregate_improvements(rows: Iterable[Dict[str, object]]) -> Tuple[Dict[str, ParcelAccumulator], int]:
    aggregates: Dict[str, ParcelAccumulator] = {}
    count = 0
    for row in rows:
        pn = _clean_parcel_number(row.get("parcel_number"))
        if not pn:
            continue
        agg = aggregates.setdefault(pn, ParcelAccumulator(parcel_number=pn))
        agg.add_row(row)
        count += 1
    return aggregates, count


def run_improvements_etl(
    *,
    roll_year: int,
    parcel: Optional[str] = None,
    dry_run: bool = False,
    batch_size: int = 500,
    fields: Optional[Sequence[str]] = None,
    stdout=None,
) -> Dict[str, object]:
    roll = AssessmentRoll.objects.filter(year=roll_year).first()
    if not roll:
        raise ValueError(f"No AssessmentRoll found for year={roll_year}")

    improvements_qs = (
        Improvements.objects.filter(roll=roll)
        .exclude(parcel_number__isnull=True)
        .exclude(parcel_number__exact="")
    )
    if parcel:
        improvements_qs = improvements_qs.filter(parcel_number=parcel)

    improvements_iterator = improvements_qs.values(
        "parcel_number",
        "plumbing_code",
        "improvement_detail_type_code",
        "improvement_detail_class_code",
        "improvement_detail_value",
        "calculated_area",
        "total_living_area",
        "condition_code",
        "effective_year_built",
        "actual_year_built",
        "new_construction_year",
        "fireplace",
    ).iterator(chunk_size=5000)

    aggregates, improvements_count = _aggregate_improvements(improvements_iterator)

    if stdout:
        stdout.write(f"Aggregated {improvements_count} improvement rows into {len(aggregates)} parcels.")

    target_parcels = list(aggregates.keys())
    if not target_parcels:
        if stdout:
            stdout.write("No parcels with improvements to update; skipping assessor updates.")
        return {
            "roll_year": roll_year,
            "roll_id": roll.id,
            "improvements_processed": improvements_count,
            "parcels_aggregated": len(aggregates),
            "assessors_processed": 0,
            "assessors_updated": 0,
            "dry_run": dry_run,
            "cleaned_assessors": 0,
            "age_updates": 0,
        }

    base_assessor_qs = Assessor.objects.filter(roll=roll, parcel_number__in=target_parcels)
    if parcel:
        base_assessor_qs = base_assessor_qs.filter(parcel_number=parcel)

    target_assessor_ids = list(base_assessor_qs.values_list("id", flat=True))
    cleaned_count = _process_code_cleaning_batch(
        Assessor.objects.filter(id__in=target_assessor_ids),
        batch_size=batch_size,
        dry_run=dry_run,
    )

    assessor_qs = Assessor.objects.filter(id__in=target_assessor_ids)

    updated_batch: list[Assessor] = []
    updated_total = 0
    processed = 0

    def _flush_batch():
        nonlocal updated_total
        if not updated_batch:
            return
        if dry_run:
            updated_total += len(updated_batch)
            updated_batch.clear()
            return
        Assessor.objects.bulk_update(updated_batch, ASSESSOR_UPDATE_FIELDS, batch_size=batch_size)
        updated_total += len(updated_batch)
        updated_batch.clear()

    with transaction.atomic():
        for assessor in assessor_qs.iterator(chunk_size=batch_size):
            processed += 1
            changed = False
            pn = _clean_parcel_number(assessor.parcel_number)
            agg = aggregates.get(pn) if pn else None
            if agg:
                if agg.apply_to_assessor(assessor, roll_year):
                    changed = True

            if changed:
                updated_batch.append(assessor)
            if len(updated_batch) >= batch_size:
                _flush_batch()

        _flush_batch()

    remaining_qs = Assessor.objects.filter(roll=roll).exclude(id__in=target_assessor_ids)
    age_updates = _process_age_batch(
        remaining_qs,
        roll_year=roll_year,
        batch_size=batch_size,
        dry_run=dry_run,
    )

    return {
        "roll_year": roll_year,
        "roll_id": roll.id,
        "improvements_processed": improvements_count,
        "parcels_aggregated": len(aggregates),
        "assessors_processed": processed,
        "assessors_updated": updated_total,
        "cleaned_assessors": cleaned_count,
        "age_updates": age_updates,
        "dry_run": dry_run,
    }
