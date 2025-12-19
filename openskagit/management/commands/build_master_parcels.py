import io
import re
import zipfile

import numpy as np
import pandas as pd
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
import datetime
from openskagit.models import MasterParcel  # adjust app name


# ---------------------------------------------------------------------
# CONSTANTS (from your notebooks)
# ---------------------------------------------------------------------

IMPROV_URL = "https://www.skagitcounty.net/Assessor/Documents/DataDownloads/Improvements.zip"
ASSESSOR_URL = "https://www.skagitcounty.net/Assessor/Documents/DataDownloads/AssessorData.zip"

# Improvements DROP_COLS
DROP_COLS_IMPROV = [
    "imprv_det_meth_cd", "rooms", "constructionstyle",
    "roofstyle", "flooring", "floorconstruction", "interiorfinish",
]

# Bathroom mapping
BATH_TOKEN_VALUES = {
    "FB": 1.0,  "MB": 1.0,  "BTH": 1.0,
    "2FB": 2.0, "3FB": 3.0,
    "QB": 0.75, "3QB": 0.75,
    "HB": 0.5,  "2HB": 1.0,
    "QTR": 0.25,
}

QUALITY_MAP = {
    "MSE": 6, "MSVG": 5, "MSVG+": 5, "MSG+": 4, "MSG": 4,
    "MSA": 3, "MSA+": 3, "MSF": 2, "MSL": 1,
}

CONDITION_MAP = {
    "E": 6, "VG": 5, "G": 4, "A": 3, "F": 2,
    "P": 1, "L": 0, "U": 3,
}

MAIN_STRUCTURE_PREFIXES = ("MA", "MW", "SW", "MH", "MF", "DW", "UF", "PM")
GARAGE_PREFIXES = ("AG", "DG", "GBI", "GAR", "CARP")
DECK_PREFIXES = ("DECK", "WDK")
PORCH_PREFIXES = ("POR", "PCH", "ENP", "SUN")
BASEMENT_PREFIXES = ("BM",)
SHOP_PREFIXES = ("SHOP", "GPB")
SHED_PREFIXES = ("SH", "SHD", "MSHD", "BU", "MPS")
POOL_PREFIXES = ("POOL", "SPL", "SPA", "HOTTUB")

EXACT_CODE_CATEGORY = {
    "ARNA": "outbuilding", "BMG": "basement", "BML": "basement",
    "BMU": "unfinished_basement", "BSMT": "basement", "C-S": "outbuilding",
    "CP": "porch", "DG1.5": "garage", "DG2": "garage", "DGAR": "garage",
    "DOCK": "outbuilding", "GREENH": "outbuilding", "GRNH": "outbuilding",
    "GARFIN": "main_structure", "LB-LOFT": "outbuilding", "LOFT": "main_structure",
    "LFT": "outbuilding", "OFP": "outbuilding", "UF1.5F": "main_structure",
    "UF1.5U": "main_structure", "UF2": "main_structure", "UF2.5F": "main_structure",
    "UF2.5U": "main_structure", "UF3": "main_structure", "MA": "main_structure",
    "MA1.5": "main_structure", "MA2": "main_structure", "MA2.5": "main_structure",
    "MA3": "main_structure",
}


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------
import pandas as pd
import numpy as np

def as_none(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or (pd.isna(v) if hasattr(pd, "isna") else False) else v

def as_int(v):
    v = as_none(v)
    return int(v) if v is not None else None

def as_float(v):
    v = as_none(v)
    return float(v) if v is not None else None

def as_bool(v):
    v = as_none(v)
    return bool(v) if v is not None else False

def normalize_parcel(p):
    if pd.isna(p):
        return None
    p = str(p).upper().strip()
    return re.sub(r"[^A-Z0-9]", "", p)


def calculate_bath_score(plumbing_str):
    if pd.isna(plumbing_str) or str(plumbing_str).strip() == "":
        return 0.0
    tokens = [t.strip().upper() for t in str(plumbing_str).split(",") if t.strip()]
    return sum(BATH_TOKEN_VALUES.get(tok, 0.0) for tok in tokens)


def classify_improvement(code):
    if not code or pd.isna(code):
        return "other"
    if code in EXACT_CODE_CATEGORY:
        return EXACT_CODE_CATEGORY[code]
    if code.startswith(MAIN_STRUCTURE_PREFIXES):
        return "main_structure"
    if code.startswith(GARAGE_PREFIXES):
        return "garage"
    if code.startswith(DECK_PREFIXES):
        return "deck"
    if code.startswith(PORCH_PREFIXES):
        return "porch"
    if code.startswith(BASEMENT_PREFIXES):
        return "basement"
    if code.startswith(SHOP_PREFIXES):
        return "shop"
    if code.startswith(SHED_PREFIXES):
        return "shed"
    if code.startswith(POOL_PREFIXES):
        return "pool"
    return "other"


def to_snake_case(name: str) -> str:
    name = name.lower()
    name = re.sub(r'[\s\-\/]', '_', name)
    name = re.sub(r'(?<!_)([a-z])([A-Z])', r'\1_\2', name)
    name = re.sub(r'_{2,}', '_', name)
    return name.strip('_')


def standardize_text_category(series: pd.Series) -> pd.Series:
    if series.dtype == "object":
        return series.str.strip().str.upper()
    return series


# ---------------------------------------------------------------------
# IMPROVEMENTS CLEAN + ROLLUP  (from ImprovementsClean.ipynb)
# ---------------------------------------------------------------------

def load_and_clean_improvements():
    print("--- LOADING IMPROVEMENTS ---")

    content = requests.get(IMPROV_URL).content
    z = zipfile.ZipFile(io.BytesIO(content))

    impr_df = pd.read_csv(
        z.open("Improvements.txt"),
        sep="|",
        engine="python",
        encoding="latin1",
        quoting=3,
        on_bad_lines="warn",
    )

    # OLD: impr_df.columns = impr_df.columns.str.lower().str.strip()
    impr_df.columns = [to_snake_case(col) for col in impr_df.columns] # <--- NEW

    impr_df = impr_df.drop(
        columns=[c for c in DROP_COLS_IMPROV if c in impr_df.columns],
        errors="ignore",
    )

    impr_df["parcelnumber"] = impr_df["parcelnumber"].apply(normalize_parcel)

    cat_cols = ["imprv_det_type_cd", "imprv_det_class_cd", "condition_cd", "building_style"]
    for c in cat_cols:
        if c in impr_df.columns:
            impr_df[c] = (
                impr_df[c]
                .astype(str)
                .str.strip()
                .str.upper()
                .replace(["NAN", "*", "NONE", "N/A"], None)
            )

    MIN_YEAR, MAX_YEAR = 1700, 2050
    for col in ["actual_year_built", "effective_yr_blt", "new_const_year"]:
        if col in impr_df.columns:
            impr_df[col] = pd.to_numeric(impr_df[col], errors="coerce")
            impr_df.loc[
                (impr_df[col] < MIN_YEAR) | (impr_df[col] > MAX_YEAR), col
            ] = None

    if "calc_area" in impr_df.columns:
        impr_df["calc_area"] = pd.to_numeric(impr_df["calc_area"], errors="coerce")
        impr_df.loc[
            (impr_df["calc_area"] <= 0) | (impr_df["calc_area"] > 50000),
            "calc_area",
        ] = None

    impr_df["improvement_category"] = impr_df["imprv_det_type_cd"].apply(
        classify_improvement
    )

    print(f"Improvements initial rows: {len(impr_df)}")
    print(f"Improvements unique parcels: {impr_df['parcelnumber'].nunique()}")

    # Dedup
    dedupe_cols = [
        "parcelnumber",
        "imprv_det_type_cd",
        "calc_area",
        "actual_year_built",
        "effective_yr_blt",
    ]
    impr_df.drop_duplicates(
        subset=[c for c in dedupe_cols if c in impr_df.columns],
        keep="first",
        inplace=True,
    )

    # Quality / Condition
    if "condition_cd" in impr_df.columns:
        impr_df["condition_score"] = impr_df["condition_cd"].map(CONDITION_MAP)

    if "imprv_det_class_cd" in impr_df.columns:
        impr_df["quality_score"] = impr_df["imprv_det_class_cd"].map(QUALITY_MAP)

    if "plumbing" in impr_df.columns:
        impr_df["bath_value"] = impr_df["plumbing"].apply(calculate_bath_score)

    columns_to_drop_raw = ["imprv_det_class_cd", "condition_cd", "plumbing"]
    impr_df.drop(
        columns=[c for c in columns_to_drop_raw if c in impr_df.columns],
        inplace=True,
        errors="ignore",
    )

    print(f"Rows after dedupe: {len(impr_df)}")
    print(
        f"Avg quality_score: {impr_df['quality_score'].mean():.2f}"
        if "quality_score" in impr_df.columns
        else "No quality_score"
    )

    # Rollup
    rollup_df = impr_df[["parcelnumber"]].drop_duplicates().set_index("parcelnumber")

    initial_rollup = impr_df.groupby("parcelnumber").agg(
        total_baths=("bath_value", "sum"),
        year_built_max=("actual_year_built", "max"),
        year_built_min=("actual_year_built", "min"),
    )
    rollup_df = rollup_df.merge(
        initial_rollup, left_index=True, right_index=True, how="left"
    )

    ROLLUP_SPEC = {
        "total_living_area": (["main_structure", "basement"], "sum"),
        "total_garage_area": (["garage"], "sum"),
        "total_deck_area": (["deck"], "sum"),
        "total_porch_area": (["porch"], "sum"),
        "total_basement_area": (["basement"], "sum"),
        "total_shop_area": (["shop"], "sum"),
        "total_shop_count": (["shop"], "size"),
        "total_shed_count": (["shed"], "size"),
        "total_shed_area": (["shed"], "sum"),
        "has_pool": (["pool"], "any"),
    }

    for new_col, (categories, agg_func) in ROLLUP_SPEC.items():
        mask = impr_df["improvement_category"].isin(categories)
        df_filtered = impr_df[mask].copy()

        agg_col = "calc_area" if agg_func == "sum" else "improvement_category"

        if agg_func == "sum":
            rollup = (
                df_filtered.groupby("parcelnumber")[agg_col]
                .sum()
                .rename(new_col)
            )
        elif agg_func == "size":
            rollup = df_filtered.groupby("parcelnumber").size().rename(new_col)
        elif agg_func == "any":
            rollup = (
                (impr_df["improvement_category"].isin(categories))
                .groupby(impr_df["parcelnumber"])
                .any()
                .rename(new_col)
            )
        else:
            continue

        rollup_df = rollup_df.merge(
            rollup, left_index=True, right_index=True, how="left"
        )

        if agg_func in ["sum", "size"]:
            if agg_func == "size":
                rollup_df[new_col] = rollup_df[new_col].fillna(0).astype(int)
            else:
                rollup_df[new_col] = rollup_df[new_col].fillna(0)
        elif agg_func == "any":
            rollup_df[new_col] = rollup_df[new_col].fillna(False)

    # Primary structure detection
    primary_candidates = impr_df[
        impr_df["improvement_category"] == "main_structure"
    ].copy()
    primary_candidates = primary_candidates.sort_values(
        by=["parcelnumber", "calc_area", "actual_year_built"],
        ascending=[True, False, False],
    )
    df_primary = primary_candidates.drop_duplicates(
        subset=["parcelnumber"], keep="first"
    )

    primary_cols = [
        "parcelnumber",
        "quality_score",
        "condition_score",
        "effective_yr_blt",
    ]
    df_primary = df_primary[primary_cols].set_index("parcelnumber")

    rollup_df = rollup_df.merge(
        df_primary, left_index=True, right_index=True, how="left"
    )

    main_structure_count = (
        impr_df[impr_df["improvement_category"] == "main_structure"]
        .groupby("parcelnumber")
        .size()
        .rename("main_structure_count")
    )
    rollup_df = rollup_df.merge(
        main_structure_count, left_index=True, right_index=True, how="left"
    )
    rollup_df["main_structure_count"] = (
        rollup_df["main_structure_count"].fillna(0).astype(int)
    )
    rollup_df["flag_multi_structure"] = rollup_df["main_structure_count"] > 1

    print("Final rollup shape:", rollup_df.shape)

    return impr_df, rollup_df


# ---------------------------------------------------------------------
# ASSESSOR CLEAN + MERGE  (from AssessorClean.ipynb)
# ---------------------------------------------------------------------

def load_and_clean_assessor_and_merge(rollup_df: pd.DataFrame) -> pd.DataFrame:
    print("\n--- STARTING ASSESSOR CLEAN PIPELINE ---")

    content = requests.get(ASSESSOR_URL).content
    z = zipfile.ZipFile(io.BytesIO(content))

    txt_files = [f for f in z.namelist() if f.lower().endswith(".txt")]
    assert len(txt_files) == 1, f"Expected 1 assessor txt file, got: {txt_files}"

    df = pd.read_csv(
        z.open(txt_files[0]),
        sep="|",
        engine="python",
        encoding="latin1",
        quoting=3,
        on_bad_lines="warn",
    )

    print(df.info())
    print(f"Loaded assessor rows: {df.shape[0]}")
    print(f"Columns: {len(df.columns)}")

    # Drop all-NaN columns from notebook
    columns_to_drop_all_nan = [
        "Old Street Number",
        "Old Street Name",
        "Old City State Zip",
    ]
    df.drop(columns=[c for c in columns_to_drop_all_nan if c in df.columns],
            inplace=True,
            errors="ignore")

    # snake_case columns
    df.columns = [to_snake_case(col) for col in df.columns]
    print("\nCleaned column names to snake_case.")

    # ID columns to string
    id_columns = ["aid", "parcel_number", "account_number", "tax_year", "appraisal_year"]
    for col in id_columns:
        if col in df.columns:
            df[col] = df[col].astype(str).replace("nan", np.nan)

    if "sale_date" in df.columns:
        df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")

    print("\nAdjusted data types for ID/Categorical columns and 'sale_date'.")

    # land_use -> land_use_code / description
    if "land_use" in df.columns:
        df[["land_use_code", "land_use_description"]] = (
            df["land_use"].str.extract(r"\((.*?)\)\s*(.*)", expand=True)
        )
        df["land_use_code"] = df["land_use_code"].replace("", np.nan)
        df["land_use_description"] = df["land_use_description"].replace("", np.nan)

        print("Top 5 extracted land_use_codes:")
        print(df["land_use_code"].value_counts().head())

    # neighborhood_code -> hood_code/description
    if "neighborhood_code" in df.columns:
        df[["hood_code", "hood_description"]] = (
            df["neighborhood_code"].str.extract(r"\((.*?)\)\s*(.*)", expand=True)
        )
        df["hood_code"] = df["hood_code"].replace("", np.nan)
        df["hood_description"] = df["hood_description"].replace("", np.nan)

        print("Top 5 extracted hood_codes:")
        print(df["hood_code"].value_counts().head())

        df.drop(columns=["land_use", "neighborhood_code"], inplace=True, errors="ignore")
        print("\nDropped original 'land_use' and 'neighborhood_code' columns.")

    # Drop redundant/sparse columns – from notebook definition
    columns_to_drop = [
        "account_number",
        "owner_name",
        "owner_add_1",
        "owner_add_2",
        "owner_add_3",
        "owner_city",
        "owner_state",
        "owner_zip",
        "legal_description",
        "exemptions",
        "building_style",
        "tot_special_assessments",
        "general_taxes",
        "inactive_date",
        "current_use_adjustment",
        "tax_year",
        "appraisal_year",
        "tax_statement_taxable_value",
        "foundation",
        "exterior_walls",
        "roof_covering",
        "roof_style",
        "floor_covering",
        "floor_construction",
        "interior_finish",
        "utilities",
        "township",
        "range",
        "section",
        "quarter_section",
        "tide_land_value",
        "senior_exemption_adjustment",
        "sale_date",
        "sale_deed_type",
        "total_taxes",
    ]
    actual_columns_to_drop = [c for c in columns_to_drop if c in df.columns]
    df.drop(columns=actual_columns_to_drop, inplace=True, errors="ignore")

    print("\n--- Missing Value Analysis (short) ---")
    missing_values = df.isnull().sum()
    missing_percent = (missing_values / len(df)) * 100
    missing_df = pd.DataFrame(
        {"Missing Count": missing_values, "Missing %": missing_percent}
    )
    missing_df = missing_df[missing_df["Missing Count"] > 0].sort_values(
        by="Missing %", ascending=False
    )
    print(missing_df.head(10))

    # year_built / eff_year_built
    if "year_built" in df.columns:
        df["year_built"] = np.where(df["year_built"] < 1800, np.nan, df["year_built"])

    if "eff_year_built" in df.columns and "year_built" in df.columns:
        df["eff_year_built"] = df["eff_year_built"].fillna(df["year_built"])

    df["year_built"] = pd.to_numeric(df["year_built"], errors="coerce").astype("Int64")
    if "eff_year_built" in df.columns:
        df["eff_year_built"] = (
            pd.to_numeric(df["eff_year_built"], errors="coerce").astype("Int64")
        )
    # after loading Assessor

    if "number_of_bedrooms" in df.columns:
        df["number_of_bedrooms"] = (
            pd.to_numeric(df["number_of_bedrooms"], errors="coerce").astype("Int64")
        )

    if "acres" in df.columns:
        df["acres"] = pd.to_numeric(df["acres"], errors="coerce")

    # id-like numeric fields
    for col in ["owner_zip", "living_area"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    print("\nKey missing counts (year_built, eff_year_built, bedrooms, acres):")
    key_cols = [c for c in ["year_built", "eff_year_built", "number_of_bedrooms", "acres"] if c in df.columns]
    print(df[key_cols].isnull().sum())

    # Categorical cleanup
    categorical_cols = [
        "parcel_number",
        "situs_street_number",
        "situs_street_name",
        "situs_city_state_zip",
        "fire_district",
        "school_district",
        "city_district",
        "prop_type",
        "land_use_description",
        "hood_description",
        "foundation",
        "exterior_walls",
        "roof_covering",
        "floor_covering",
        "heat_air_cond",
        "fireplace",
    ]

    for col in categorical_cols:
        if col in df.columns:
            df[col] = standardize_text_category(df[col])

    # Rename prop_type -> proptype so later filter works
    if "prop_type" in df.columns and "proptype" not in df.columns:
        df.rename(columns={"prop_type": "proptype"}, inplace=True)

    for drop_col in ["plumbing", "unit"]:
        if drop_col in df.columns:
            df.drop(columns=[drop_col], inplace=True)

    situs_cols = ["situs_street_number", "situs_street_name", "situs_city_state_zip"]
    if all(col in df.columns for col in situs_cols):
        df["situs_address"] = (
            df["situs_street_number"].fillna("")
            + " "
            + df["situs_street_name"].fillna("")
            + " "
            + df["situs_city_state_zip"].fillna("")
        ).str.strip()
        df.drop(columns=situs_cols, inplace=True)

    print("\nSample cleaned rows:")
    print(df.head())

    # Filter by proptype: remove 'P', 'C'
    if "proptype" in df.columns:
        initial_rows = len(df)
        df = df[~df["proptype"].isin(["P", "C"])].copy()
        rows_removed = initial_rows - len(df)
        print(f"\nRemoved {rows_removed} rows with proptype in ['P','C']")
        print("Remaining proptype counts:")
        print(df["proptype"].value_counts().head())

    # Normalise parcel number
    if "parcel_number" in df.columns:
        df["parcel_number"] = df["parcel_number"].apply(normalize_parcel)

    # Merge with improvements rollup
    impr = rollup_df.copy()
    current_year = datetime.datetime.now().year
    
    # Property Age
    if "final_eff_yr_blt" in df.columns: # Use the name it will be after final merge
        df['property_age'] = current_year - df['eff_year_built'] # Use eff_year_built from assessor
    
    # Price Per Square Foot (using assessor data before merge)
    if 'sale_price' in df.columns and 'living_area' in df.columns:
        living_area_float = df['living_area'].astype(float)
        df['price_per_sqft'] = np.where(
            living_area_float > 0,
            df['sale_price'] / living_area_float,
            np.nan
        )
    
    # Log Transforms
    for col in ['total_market_value', 'building_value', 'sale_price']:
        if col in df.columns:
            df[f'log_{col}'] = np.log1p(df[col])
    
    print("\nApplied Feature Engineering (Age, PSF, Log Transforms).")


    impr.index.name = "parcel_number"
    impr = impr.reset_index()
    impr["parcel_number"] = impr["parcel_number"].apply(normalize_parcel)

    master = df.merge(impr, on="parcel_number", how="left")

    # Precompute unified final fields for dedup sorting
    if "total_living_area" in master.columns and "living_area" in master.columns:
        master["final_living_area"] = master["total_living_area"].fillna(
            master["living_area"]
        )
    else:
        master["final_living_area"] = np.nan

    if "year_built_min" in master.columns and "year_built" in master.columns:
        master["final_year_built"] = master["year_built_min"].fillna(
            master["year_built"]
        )
    else:
        master["final_year_built"] = master.get("year_built")

    if "total_garage_area" in master.columns:
        master["final_garage_area"] = master["total_garage_area"]
    else:
        master["final_garage_area"] = np.nan

    if "effective_yr_blt" in master.columns and "eff_year_built" in master.columns:
        master["final_eff_yr_blt"] = master["effective_yr_blt"].fillna(
            master["eff_year_built"]
        )
    else:
        master["final_eff_yr_blt"] = master.get("eff_year_built")
    # after you build `master` (right before write_master_to_db)
    master["_is_res"] = master["proptype"].eq("R")
    area_candidates = [
        col for col in ["final_living_area", "total_living_area", "living_area"]
        if col in master.columns
    ]
    if area_candidates:
        master["_has_area"] = (
            master[area_candidates].max(axis=1).fillna(0) > 0
        )
    else:
        master["_has_area"] = False
    master["_tmv"]      = master["total_market_value"].fillna(-1)
    master["_yr"]       = master["final_year_built"].fillna(-1)

    master = (master
        .sort_values(
            ["parcel_number","_is_res","_has_area","_tmv","_yr"],
            ascending=[True, False, False, False, False]
        )
        .drop_duplicates(subset=["parcel_number"], keep="first")
        .drop(columns=["_is_res","_has_area","_tmv","_yr"])
    )

    print("\nMaster merged shape:", master.shape)
    return master


# ---------------------------------------------------------------------
# WRITE TO DJANGO
# ---------------------------------------------------------------------

def write_master_to_db(master: pd.DataFrame):
    print("\n--- WRITING TO MasterParcel (DELETE + REBUILD) ---")

    with transaction.atomic():
        MasterParcel.objects.all().delete()

        objs = []
        for row in master.itertuples():
            # in write_master_to_db(), inside loop:
            objs.append(MasterParcel(
                parcel_number=as_none(getattr(row, "parcel_number", None)),
                aid=as_int(getattr(row, "aid", None)),

                building_value=as_float(getattr(row, "building_value", None)),
                impr_land_value=as_float(getattr(row, "impr_land_value", None)),
                unimpr_land_value=as_float(getattr(row, "unimpr_land_value", None)),
                timber_land_value=as_float(getattr(row, "timber_land_value", None)),
                assessed_value=as_float(getattr(row, "assessed_value", None)),
                taxable_value=as_float(getattr(row, "taxable_value", None)),
                total_market_value=as_float(getattr(row, "total_market_value", None)),
                acres=as_float(getattr(row, "acres", None)),
                sale_price=as_float(getattr(row, "sale_price", None)),

                year_built=as_int(getattr(row, "year_built", None)),
                living_area=as_int(getattr(row, "living_area", None)),
                heat_air_cond=as_none(getattr(row, "heat_air_cond", None)),
                fireplace=as_none(getattr(row, "fireplace", None)),
                finishedbasement=as_int(getattr(row, "finishedbasement", None)),
                number_of_bedrooms=as_int(getattr(row, "number_of_bedrooms", None)),
                eff_year_built=as_int(getattr(row, "eff_year_built", None)),
                unfinishedbasement=as_int(getattr(row, "unfinishedbasement", None)),

                fire_district=as_none(getattr(row, "fire_district", None)),
                school_district=as_none(getattr(row, "school_district", None)),
                city_district=as_none(getattr(row, "city_district", None)),
                levy_code=as_none(getattr(row, "levy_code", None)),

                proptype=as_none(getattr(row, "proptype", None)),
                land_use_code=as_none(getattr(row, "land_use_code", None)),
                land_use_description=as_none(getattr(row, "land_use_description", None)),
                hood_code=as_none(getattr(row, "hood_code", None)),
                hood_description=as_none(getattr(row, "hood_description", None)),
                situs_address=as_none(getattr(row, "situs_address", None)),

                total_baths=as_float(getattr(row, "total_baths", None)),
                year_built_max=as_int(getattr(row, "year_built_max", None)),
                year_built_min=as_int(getattr(row, "year_built_min", None)),
                total_living_area=as_float(getattr(row, "total_living_area", None)),
                total_garage_area=as_float(getattr(row, "total_garage_area", None)),
                total_deck_area=as_float(getattr(row, "total_deck_area", None)),
                total_porch_area=as_float(getattr(row, "total_porch_area", None)),
                total_basement_area=as_float(getattr(row, "total_basement_area", None)),
                total_shop_area=as_float(getattr(row, "total_shop_area", None)),
                total_shop_count=as_int(getattr(row, "total_shop_count", None)),
                total_shed_count=as_int(getattr(row, "total_shed_count", None)),
                total_shed_area=as_float(getattr(row, "total_shed_area", None)),
                has_pool=as_bool(getattr(row, "has_pool", False)),
                quality_score=as_float(getattr(row, "quality_score", None)),
                condition_score=as_float(getattr(row, "condition_score", None)),
                effective_yr_blt=as_int(getattr(row, "effective_yr_blt", None)),
                main_structure_count=as_int(getattr(row, "main_structure_count", None)),
                flag_multi_structure=as_bool(getattr(row, "flag_multi_structure", False)),

                final_living_area=as_float(getattr(row, "final_living_area", None)),
                final_year_built=as_int(getattr(row, "final_year_built", None)),
                final_garage_area=as_float(getattr(row, "final_garage_area", None)),
                final_eff_yr_blt=as_int(getattr(row, "final_eff_yr_blt", None)),
            ))



        MasterParcel.objects.bulk_create(objs, batch_size=1000)

    print("MasterParcel rebuild complete.")


# ---------------------------------------------------------------------
# MANAGEMENT COMMAND
# ---------------------------------------------------------------------

class Command(BaseCommand):
    help = "Download, clean, roll up, merge, and rebuild MasterParcel."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== BUILDING MASTER PARCEL ==="))

        # 1) Improvements: clean + rollup
        impr_df, rollup_df = load_and_clean_improvements()

        # 2) Assessor: clean + merge with rollup
        master_df = load_and_clean_assessor_and_merge(rollup_df)

        # 3) Write to DB (delete + rebuild)
        write_master_to_db(master_df)

        self.stdout.write(self.style.SUCCESS("=== MASTER PARCEL REBUILD DONE ==="))
