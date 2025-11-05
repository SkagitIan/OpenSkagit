from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .models import Improvements


# Friendly label mappings
QUALITY_LABELS: Dict[str, str] = {
    "MSL": "Low",
    "MSF": "Fair",
    "MSA": "Average",
    "MSG": "Good",
    "MSVG": "Very Good",
    "MSE": "Excellent",
}

QUALITY_WEIGHTS: Dict[str, int] = {
    "MSL": 1,
    "MSF": 2,
    "MSA": 3,
    "MSG": 4,
    "MSVG": 5,
    "MSE": 6,
}

CONDITION_LABELS: Dict[str, str] = {
    "E": "Excellent",
    "VG": "Very Good",
    "G": "Good",
    "A": "Average",
    "F": "Fair",
    "P": "Poor",
    "l": "Low"
}

# Improvement detail type friendly labels (extend as codes are discovered)
TYPE_LABELS: Dict[str, str] = {
    "MA": "Main Area",
    "CWP": "Covered Porch",
}

# Friendly improvement labels sourced from assessor documentation
IMPROVEMENT_LABELS: Dict[str, str] = {
    "MA": "Main Area",
    "MA-SPLIT": "Split Entry Home (Upper Floor Area)",
    "MA-TRI": "Tri-Level Home (Main and Upper Floors)",
    "MA1.5F": "1.5 Story Home with Finished Upper Floor",
    "MA1.5U": "1.5 Story Home with Unfinished Upper Floor",
    "MA2": "Two Story Home (Main Level)",
    "MA2.5F": "2.5 Story Home with Finished Top Floor",
    "MA2.5U": "2.5 Story Home with Unfinished Top Floor",
    "UF1.5F": "Finished Upper Level in 1.5 Story Home",
    "UF1.5U": "Unfinished Upper Level in 1.5 Story Home",
    "UF2": "Second Floor Living Area",
    "UF2.5F": "Finished Upper Floor in 2.5 Story Home",
    "UF2.5U": "Unfinished Upper Floor in 2.5 Story Home",
    "AGAR": "Attached Garage (Single Story)",
    "AG1.5": "Attached Garage with Loft or Partial Upper Room",
    "AG2": "Attached Garage with Full Upper Room",
    "DGAR": "Detached Garage (Single Story)",
    "DG1.5": "Detached Garage with Loft or Partial Upper Room",
    "DG2": "Detached Garage with Full Upper Room",
    "GBI": "Built-In Garage (Part of Main Structure)",
    "CARP": "Carport (Open-Sided Shelter)",
    "LOFT": "Loft Above Garage or Outbuilding",
    "GARFIN": "Finished Room Attached to Garage (Rec Room or Apartment)",
    "BMU": "Unfinished Basement",
    "BML": "Basement with Basic or Low-Quality Finish",
    "BMF": "Finished Basement (Similar to Main Living Area)",
    "BMG": "Basement Garage",
    "BMT": "Tri-Level Basement",
    "CP": "Concrete Patio",
    "CCP": "Covered Concrete Patio",
    "DECK": "Wood Deck",
    "CWP": "Covered Wood Deck",
    "ENP": "Enclosed or Covered Porch",
    "SUN": "Sunroom or Glass Solarium",
    "BBQ": "Built-In Barbecue Area",
    "OFP": "Outdoor Fireplace",
    "OS": "Outdoor Sink or Kitchen Feature",
    "C-S": "Cabin or Studio (Guest or Hobby Space)",
    "MPS": "Multi-Purpose Shed or Workshop",
    "RC": "Roof Cover or Shelter",
    "LT": "Lean-To or Open-Sided Shelter",
    "SW": "Single-Wide Manufactured Home",
    "MW": "Double-Wide or Multi-Wide Manufactured Home",
    "PM": "Park Model Home",
    "ARNA": "Indoor or Covered Arena",
    "BUNK": "Bunker or Feed Storage Silo",
    "FDB": "Feeder Barn",
    "FSB": "Free-Stall Barn (Livestock Shelter)",
    "GPB": "General Purpose Barn or Building",
    "GPBFIN": "General Purpose Building with Finished Living Space",
    "GREENH": "Greenhouse",
    "HRC": "Hay Cover or Roofed Storage Area",
    "HSTB": "Hobby Stable or Small Animal Barn",
    "LFT": "Loft Area (Used with Barn or Outbuilding)",
    "LB": "Loft Barn",
    "MSHD": "Machine Shed or Equipment Storage",
    "LAGOON": "Manure Lagoon or Waste Pond",
    "MCB": "Metal Building (Commercial or Agricultural)",
    "MLKB": "Milk Barn",
    "MP": "Milk Parlor",
    "PS": "Potato or Crop Storage Building",
    "PLH": "Poultry Laying House or Chicken Barn",
}

# Group improvements into broad buckets for iconography
IMPROVEMENT_CATEGORIES: Dict[str, str] = {
    "MA": "home",
    "MA1.5": "home",
    "MA2": "home",
    "MA2.5": "home",
    "UF": "home",
    "SW": "home",
    "MW": "home",
    "PM": "home",
    "AG": "garage",
    "DG": "garage",
    "GBI": "garage",
    "GAR": "garage",
    "CARP": "garage",
    "LOFT": "garage",
    "BM": "home",
    "CP": "amenity",
    "CCP": "amenity",
    "DECK": "amenity",
    "CWP": "amenity",
    "ENP": "amenity",
    "SUN": "amenity",
    "BBQ": "amenity",
    "OFP": "amenity",
    "OS": "amenity",
    "C-S": "outbuilding",
    "MPS": "outbuilding",
    "RC": "outbuilding",
    "LT": "outbuilding",
    "AR": "outbuilding",
    "BU": "outbuilding",
    "FD": "outbuilding",
    "FS": "outbuilding",
    "GPB": "outbuilding",
    "GREENH": "outbuilding",
    "HR": "outbuilding",
    "HS": "outbuilding",
    "LF": "outbuilding",
    "LB": "outbuilding",
    "MSHD": "outbuilding",
    "LAG": "amenity",
    "MCB": "outbuilding",
    "ML": "outbuilding",
    "MP": "outbuilding",
    "PS": "outbuilding",
    "PLH": "outbuilding",
}


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().upper()


def quality_label(code: Optional[str]) -> Optional[str]:
    key = _norm(code)
    if not key:
        return None
    return QUALITY_LABELS.get(key, code)


def condition_label(code: Optional[str]) -> Optional[str]:
    key = _norm(code)
    if not key:
        return None
    return CONDITION_LABELS.get(key, code)


def type_label(code: Optional[str]) -> Optional[str]:
    key = _norm(code)
    if not key:
        return None
    # Preserve MAx subtypes as Main Area
    if key.startswith("MA"):
        return IMPROVEMENT_LABELS.get("MA")
    return IMPROVEMENT_LABELS.get(key, code)


def improvement_label(code: Optional[str]) -> Optional[str]:
    key = _norm(code)
    if not key:
        return None
    return IMPROVEMENT_LABELS.get(key, TYPE_LABELS.get(key, code))


def improvement_category(code: Optional[str]) -> str:
    key = _norm(code)
    if not key:
        return "other"
    for prefix, category in IMPROVEMENT_CATEGORIES.items():
        if key.startswith(prefix):
            return category
    return "other"


def building_style_label(style: Optional[str]) -> Optional[str]:
    # Building style typically comes human-readable from the roll (e.g., "TWO STORY").
    # Normalize capitalization lightly; leave unknowns unchanged.
    if not style:
        return None
    text = str(style).strip()
    if not text:
        return None
    # Title-case common patterns while preserving numerals/fractions.
    return text.title()


def _parse_main_area_story(type_code: str) -> Optional[str]:
    """
    Return story indicator from a type code (e.g., MA, MA1.5, MA2 -> '1', '1.5', '2').
    Defaults MA -> '1'.
    """
    code = _norm(type_code)
    if not code.startswith("MA"):
        return None
    suffix = code[2:]
    if not suffix:
        return "1"
    # Accept formats like '1', '1.5', '2', '2.5'
    try:
        # Validate it parses as float; return original string form
        float(suffix.replace("_", "."))
        return suffix.replace("_", ".")
    except Exception:
        return None


def _dedupe_rows(rows: Iterable[Improvements]) -> List[Improvements]:
    """
    Deduplicate by (improvement_id, detail_type) to avoid dropping distinct structures.

    Some detail rows lack an improvement_id; we always keep those.
    """
    results: List[Improvements] = []
    seen: set = set()
    for row in rows:
        type_code = _norm(getattr(row, "improvement_detail_type_code", None))
        impr_id = getattr(row, "improvement_id", None)
        if impr_id in (None, "", 0):
            results.append(row)
            continue
        key = (impr_id, type_code)
        if key in seen:
            continue
        seen.add(key)
        results.append(row)
    return results


def rollup_for_parcel(
    parcel_number: str,
    *,
    roll_year: Optional[int] = None,
    roll_id: Optional[int] = None,
    assessor_building_style: Optional[str] = None,
) -> Dict[str, object]:
    """
    Aggregate improvement details for a parcel into a compact, display-ready structure.

    Returns keys:
      - style: Optional[str]
      - quality: Optional[str]
      - condition: Optional[str]
      - main_area: { total_sqft: Optional[int], by_story: Dict[str, int] }
      - components: List[{ code, label, count, total_sqft }]
    """
    qs = Improvements.objects.filter(parcel_number=parcel_number)
    # Filter by roll id when available; otherwise fall back to roll year.
    if roll_id is not None:
        qs = qs.filter(roll_id=roll_id)
    elif roll_year is not None:
        qs = qs.filter(roll__year=roll_year)

    # Prefer most recent/valuable record per improvement_id
    rows = (
        qs.order_by(
            "improvement_id",
            "-effective_year_built",
            "-actual_year_built",
            "-improvement_detail_value",
            "-id",
        )
    )
    rows = _dedupe_rows(rows)

    main_area_total = 0.0
    main_area_by_story: Dict[str, float] = defaultdict(float)
    main_area_codes: Dict[str, float] = defaultdict(float)
    quality_candidates: List[str] = []
    condition_candidates: List[str] = []
    components_area: Dict[str, float] = defaultdict(float)
    components_count: Dict[str, int] = defaultdict(int)
    style_value: Optional[str] = None

    for row in rows:
        type_code = _norm(row.improvement_detail_type_code)
        if not type_code:
            continue
        # pick an MA-style building style if present; otherwise fall back later
        if not style_value and row.building_style:
            style_value = building_style_label(row.building_style)

        area = row.calculated_area or row.total_living_area or 0
        try:
            area_val = float(area or 0)
        except Exception:
            area_val = 0.0

        if type_code.startswith("MA"):
            story = _parse_main_area_story(type_code) or "1"
            main_area_by_story[story] += area_val
            main_area_total += area_val
            main_area_codes[type_code] += area_val
            if row.improvement_detail_class_code:
                quality_candidates.append(_norm(row.improvement_detail_class_code))
            if row.condition_code:
                condition_candidates.append(_norm(row.condition_code))
        else:
            components_area[type_code] += area_val
            components_count[type_code] += 1

    # Choose quality — prefer the highest-weight candidate among most common
    quality_choice: Optional[str] = None
    if quality_candidates:
        freq = Counter(quality_candidates)
        most_common = [code for code, _ in freq.most_common()]
        if most_common:
            quality_choice = max(most_common, key=lambda c: QUALITY_WEIGHTS.get(c, 0))

    # Choose condition — prefer the mode; on ties pick "best"
    condition_choice: Optional[str] = None
    if condition_candidates:
        freq = Counter(condition_candidates)
        if freq:
            top_count = freq.most_common(1)[0][1]
            top_codes = [code for code, count in freq.items() if count == top_count]
            order = {"P": 0, "F": 1, "A": 2, "G": 3, "VG": 4, "E": 5}
            condition_choice = max(top_codes, key=lambda c: order.get(c, -1))

    # Fallback style from assessor if not present in improvements
    if not style_value and assessor_building_style:
        style_value = building_style_label(assessor_building_style)

    fallback_primary_code: Optional[str] = None
    if not main_area_codes and components_area:
        fallback_primary_code = max(components_area.items(), key=lambda kv: kv[1])[0]

    components: List[Dict[str, object]] = []
    for code, total in sorted(components_area.items(), key=lambda kv: kv[1], reverse=True):
        if fallback_primary_code and code == fallback_primary_code:
            continue
        display_label = improvement_label(code)
        components.append(
            {
                "code": code,
                "label": display_label or type_label(code),
                "count": components_count.get(code, 0),
                "total_sqft": int(round(total)) if total else None,
                "category": improvement_category(code),
            }
        )

    # Normalize main area numbers to ints for display
    by_story_int: Dict[str, int] = {
        story: int(round(val)) for story, val in main_area_by_story.items() if val
    }

    primary_code: Optional[str] = None
    primary_total: Optional[float] = None
    if main_area_codes:
        primary_code = max(main_area_codes.items(), key=lambda kv: kv[1])[0]
        primary_total = main_area_total
    elif fallback_primary_code:
        primary_code = fallback_primary_code
        primary_total = components_area.get(primary_code, 0.0)

    primary_label = improvement_label(primary_code)

    rollup: Dict[str, object] = {
        "style": style_value,
        "quality": quality_label(quality_choice),
        "quality_code": quality_choice,
        "condition": condition_label(condition_choice),
        "condition_code": condition_choice,
        "main_area": {
            "total_sqft": int(round(main_area_total)) if main_area_total else None,
            "by_story": by_story_int,
        },
        "components": components,
        "primary": {
            "code": primary_code,
            "label": primary_label or building_style_label(style_value) or "Home",
            "building_style": style_value,
            "total_sqft": int(round(primary_total)) if primary_total else None,
            "category": improvement_category(primary_code),
        },
    }
    return rollup
