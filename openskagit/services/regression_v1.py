from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from django.conf import settings
from django.db import connection
from statsmodels.stats.outliers_influence import OLSInfluence


RUNS_DIR = Path(settings.BASE_DIR) / "data" / "regression_v1_runs"

DEFAULT_PREDICTORS = [
    "log_area",
    "log_lot",
    "log_age",
    "quality_score",
    "condition_score",
    "bedrooms",
    "bathrooms",
    "has_garage",
    "has_basement",
    "land_share",
    "months_to_anchor",
]

INTERACTION_DEFINITIONS: Dict[str, Tuple[str, str]] = {
    "area_quality": ("log_area", "quality_score"),
    "area_condition": ("log_area", "condition_score"),
    "lot_quality": ("log_lot", "quality_score"),
}

DEFAULT_INTERACTION_TERMS = [
    "area_quality",
    "area_condition",
]


@dataclass
class RegressionSettings:
    mode: str = "sfr"
    anchor_date: Optional[str] = None
    training_years: int = 10
    min_neighborhood_n: int = 30
    min_segment_n: int = 120
    ratio_min: float = 0.50
    ratio_max: float = 2.00
    residual_z_max: float = 2.5
    iqr_multiplier: float = 1.5
    east_lon_threshold: float = -122.28221
    west_lon_threshold: float = -122.36921
    predictors: List[str] = field(default_factory=lambda: list(DEFAULT_PREDICTORS))
    interaction_terms: List[str] = field(default_factory=lambda: list(DEFAULT_INTERACTION_TERMS))
    enable_neighborhood_scalars: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "anchor_date": self.anchor_date,
            "training_years": self.training_years,
            "min_neighborhood_n": self.min_neighborhood_n,
            "min_segment_n": self.min_segment_n,
            "ratio_min": self.ratio_min,
            "ratio_max": self.ratio_max,
            "residual_z_max": self.residual_z_max,
            "iqr_multiplier": self.iqr_multiplier,
            "east_lon_threshold": self.east_lon_threshold,
            "west_lon_threshold": self.west_lon_threshold,
            "predictors": list(self.predictors),
            "interaction_terms": list(self.interaction_terms),
            "enable_neighborhood_scalars": self.enable_neighborhood_scalars,
        }


@dataclass
class SegmentAssignment:
    frame: pd.DataFrame
    hood_map: List[Dict[str, Any]]
    segment_counts: Dict[str, int]


@dataclass
class SegmentModelResult:
    segment_key: str
    valuation_area: str
    n_total: int
    n_train: int
    n_validate: int
    n_fit: int
    predictors: List[str]
    coefficients: Dict[str, float]
    coefficient_se: Dict[str, float]
    segment_scalar: float
    neighborhood_scalars: Dict[str, float]
    metrics: Dict[str, Any]
    outlier_counts: Dict[str, int]


@dataclass
class RegressionRunResult:
    run_id: str
    status: str
    settings: Dict[str, Any]
    segment_summary: List[Dict[str, Any]]
    global_metrics: Dict[str, Any]
    diagnostics_path: str
    coefficients: List[Dict[str, Any]]
    segment_map: List[Dict[str, Any]]


def default_regression_settings() -> RegressionSettings:
    return RegressionSettings()


def parse_settings(payload: Optional[Dict[str, Any]] = None) -> RegressionSettings:
    payload = payload or {}

    def _as_int(name: str, default: int) -> int:
        value = payload.get(name, default)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc

    def _as_float(name: str, default: float) -> float:
        value = payload.get(name, default)
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc

    predictors = payload.get("predictors", DEFAULT_PREDICTORS)
    if isinstance(predictors, str):
        predictors = [p.strip() for p in predictors.split(",") if p.strip()]

    interaction_terms = payload.get("interaction_terms", DEFAULT_INTERACTION_TERMS)
    if isinstance(interaction_terms, str):
        interaction_terms = [p.strip() for p in interaction_terms.split(",") if p.strip()]

    valid_interactions = [name for name in interaction_terms if name in INTERACTION_DEFINITIONS]

    settings_obj = RegressionSettings(
        mode=str(payload.get("mode", "sfr") or "sfr").strip().lower(),
        anchor_date=(str(payload.get("anchor_date")).strip() if payload.get("anchor_date") else None),
        training_years=max(1, _as_int("training_years", 10)),
        min_neighborhood_n=max(5, _as_int("min_neighborhood_n", 30)),
        min_segment_n=max(20, _as_int("min_segment_n", 120)),
        ratio_min=max(0.01, _as_float("ratio_min", 0.50)),
        ratio_max=max(0.10, _as_float("ratio_max", 2.00)),
        residual_z_max=max(0.5, _as_float("residual_z_max", 2.5)),
        iqr_multiplier=max(0.1, _as_float("iqr_multiplier", 1.5)),
        east_lon_threshold=_as_float("east_lon_threshold", -122.28221),
        west_lon_threshold=_as_float("west_lon_threshold", -122.36921),
        predictors=[p for p in predictors if p],
        interaction_terms=valid_interactions,
        enable_neighborhood_scalars=bool(payload.get("enable_neighborhood_scalars", True)),
    )

    if settings_obj.ratio_min >= settings_obj.ratio_max:
        raise ValueError("ratio_min must be smaller than ratio_max")
    if settings_obj.west_lon_threshold >= settings_obj.east_lon_threshold:
        raise ValueError("west_lon_threshold must be smaller than east_lon_threshold")
    if settings_obj.mode != "sfr":
        raise ValueError("Only 'sfr' mode is supported in regression_v1")

    return settings_obj


def _map_valuation_area(hood_code: Optional[str]) -> str:
    text = (hood_code or "").strip().upper()
    if not text:
        return "OTHER"
    if text.startswith(("20B", "21B", "22B", "23B", "26B", "27B")):
        return "BURLINGTON"
    if text.startswith(("20LC", "21LC", "22LC", "23LC", "20CON", "22CON")):
        return "LACONNER_CONWAY"
    if text.startswith(("20A", "21A", "22A", "23A", "20FID", "22FID", "20GUEM", "22GUEM")):
        return "ANACORTES"
    if text.startswith(("20SW", "21SW", "22SW", "23SW")):
        return "SEDRO_WOOLLEY"
    if text.startswith(("20CC", "22CC", "10CC")):
        return "CONCRETE"
    if text.startswith(("20MV", "21MV", "22MV", "23MV")):
        return "MOUNT_VERNON"
    return "OTHER"


def _geo_bucket(lon: Optional[float], cfg: RegressionSettings) -> str:
    if lon is None or (isinstance(lon, float) and math.isnan(lon)):
        return "UNKNOWN"
    if lon <= cfg.west_lon_threshold:
        return "WEST_COAST_ISLANDS"
    if lon <= cfg.east_lon_threshold:
        return "CENTRAL_VALLEY"
    return "EAST_COUNTY"


def _is_east_macro(valuation_area: str, geo_bucket: str, hood_code: Optional[str]) -> bool:
    code = (hood_code or "").strip().upper()
    if geo_bucket == "EAST_COUNTY":
        return True
    if valuation_area == "CONCRETE":
        return True
    if code.startswith(("20CC", "22CC", "10CC")):
        return True
    return False


def _load_hood_longitudes() -> Dict[str, float]:
    sql = """
    SELECT code AS hood_code, ST_X(ST_Centroid(geom_4326)) AS lon
    FROM openskagit_neighborhoodgeom
    """
    df = pd.read_sql_query(sql, connection)
    if df.empty:
        return {}
    return {
        str(row["hood_code"]): float(row["lon"])
        for _, row in df.iterrows()
        if row["hood_code"] is not None and pd.notna(row["lon"])
    }


def _load_sales_frame() -> pd.DataFrame:
    sql = """
    SELECT
      s.id AS sale_id,
      s.parcel_number,
      s.sale_price::double precision AS sale_price,
      s.sale_date::timestamp without time zone AS sale_date,
      mp.hood_code,
      COALESCE(mp.hood_description, '') AS hood_description,
      mp.total_market_value::double precision AS total_market_value,
      COALESCE(mp.final_living_area, mp.total_living_area, mp.living_area)::double precision AS living_area,
      COALESCE(mp.acres, 0)::double precision AS lot_acres,
      COALESCE(mp.final_year_built, mp.year_built, mp.year_built_max)::double precision AS year_built,
      COALESCE(mp.quality_score, 0)::double precision AS quality_score,
      COALESCE(mp.condition_score, 0)::double precision AS condition_score,
      COALESCE(mp.number_of_bedrooms, 0)::double precision AS bedrooms,
      COALESCE(mp.total_baths, 0)::double precision AS bathrooms,
      CASE WHEN COALESCE(mp.final_garage_area, mp.total_garage_area, 0) > 0 THEN 1.0 ELSE 0.0 END AS has_garage,
      CASE
        WHEN COALESCE(mp.total_basement_area, 0) > 0
          OR COALESCE(mp.finishedbasement, 0) > 0
          OR COALESCE(mp.unfinishedbasement, 0) > 0
        THEN 1.0 ELSE 0.0
      END AS has_basement,
      (COALESCE(mp.impr_land_value, 0) + COALESCE(mp.unimpr_land_value, 0))::double precision AS land_market_value
    FROM sales s
    JOIN master_parcel mp ON mp.parcel_number = s.parcel_number
    WHERE s.sale_type = 'VALID SALE'
      AND s.sale_price > 10000
      AND s.sale_date >= DATE '2010-01-01'
      AND COALESCE(mp.proptype, '') = 'R'
      AND NULLIF(TRIM(mp.land_use_code), '') IS NOT NULL
      AND TRIM(mp.land_use_code) ~ '^\\d+$'
      AND TRIM(mp.land_use_code)::int IN (110, 111, 112, 113)
      AND COALESCE(COALESCE(mp.final_living_area, mp.total_living_area, mp.living_area), 0) > 0
      AND COALESCE(mp.acres, 0) > 0
    """
    df = pd.read_sql_query(sql, connection)
    if df.empty:
        return df
    df["sale_date"] = pd.to_datetime(df["sale_date"])
    return df


def _apply_training_window(df: pd.DataFrame, cfg: RegressionSettings) -> pd.DataFrame:
    if df.empty:
        return df
    max_sale_date = df["sale_date"].max()
    cutoff_date = max_sale_date - pd.DateOffset(years=cfg.training_years)
    return df[df["sale_date"] >= cutoff_date].copy()


def _resolve_anchor_date(df: pd.DataFrame, cfg: RegressionSettings) -> dt.date:
    if cfg.anchor_date:
        return dt.date.fromisoformat(cfg.anchor_date)
    max_sale_date = df["sale_date"].max()
    anchor_year = int(max_sale_date.year) + 1
    return dt.date(anchor_year, 1, 1)


def _build_features(df: pd.DataFrame, cfg: RegressionSettings, anchor_date: dt.date) -> pd.DataFrame:
    out = df.copy()
    out["valuation_area"] = out["hood_code"].apply(_map_valuation_area)

    anchor_ts = pd.Timestamp(anchor_date)
    out["months_to_anchor"] = (anchor_ts - out["sale_date"]).dt.days / 30.4375

    reference_year = anchor_date.year
    out["age"] = (reference_year - out["year_built"].fillna(reference_year)).clip(lower=0)

    out["log_area"] = np.log(out["living_area"].clip(lower=1.0))
    out["log_lot"] = np.log1p(out["lot_acres"].clip(lower=0.0))
    out["log_age"] = np.log1p(out["age"].clip(lower=0.0))

    with np.errstate(divide="ignore", invalid="ignore"):
        land_share = out["land_market_value"] / out["total_market_value"].replace(0, np.nan)
    out["land_share"] = land_share.clip(lower=0.0, upper=1.0).fillna(0.0)

    for term in cfg.interaction_terms:
        definition = INTERACTION_DEFINITIONS.get(term)
        if not definition:
            continue
        left, right = definition
        if left in out.columns and right in out.columns:
            out[term] = out[left] * out[right]

    out["raw_ratio"] = out["sale_price"] / out["total_market_value"].replace(0, np.nan)
    out = out.replace([np.inf, -np.inf], np.nan)

    predictor_cols = [p for p in cfg.predictors if p in out.columns]
    for term in cfg.interaction_terms:
        if term in out.columns and term not in predictor_cols:
            predictor_cols.append(term)

    # Coerce model features to finite values with simple medians.
    for col in predictor_cols:
        median_value = out[col].median() if out[col].notna().any() else 0.0
        out[col] = out[col].fillna(median_value)

    return out


def assign_segments(df: pd.DataFrame, cfg: RegressionSettings, hood_lon_map: Dict[str, float]) -> SegmentAssignment:
    out = df.copy()
    out["hood_code"] = out["hood_code"].fillna("").astype(str)
    out["hood_lon"] = out["hood_code"].map(hood_lon_map)
    out["geo_bucket"] = out["hood_lon"].apply(lambda lon: _geo_bucket(lon, cfg))
    out["is_east_macro"] = out.apply(
        lambda row: _is_east_macro(
            str(row.get("valuation_area") or "OTHER"),
            str(row.get("geo_bucket") or "UNKNOWN"),
            str(row.get("hood_code") or ""),
        ),
        axis=1,
    )

    hood_counts = out.groupby("hood_code").size().to_dict()

    def _base_segment(row: pd.Series) -> str:
        hood = str(row.get("hood_code") or "")
        if hood and hood_counts.get(hood, 0) >= cfg.min_neighborhood_n:
            return f"hood:{hood}"
        if bool(row.get("is_east_macro")):
            return "macro:EAST_COUNTY"
        return f"area:{row.get('valuation_area', 'OTHER')}"

    out["segment_key"] = out.apply(_base_segment, axis=1)

    segment_counts = out["segment_key"].value_counts().to_dict()

    def _secondary_segment(row: pd.Series) -> str:
        current_segment = str(row.get("segment_key") or "")
        current_count = int(segment_counts.get(current_segment, 0))
        if current_count >= cfg.min_segment_n:
            return current_segment

        if current_segment.startswith("hood:"):
            if bool(row.get("is_east_macro")):
                return "macro:EAST_COUNTY"
            return f"area:{row.get('valuation_area', 'OTHER')}"

        if current_segment == "macro:EAST_COUNTY":
            return f"area:{row.get('valuation_area', 'OTHER')}"

        if current_segment.startswith("area:"):
            return "county:COUNTYWIDE"

        return "county:COUNTYWIDE"

    out["segment_key"] = out.apply(_secondary_segment, axis=1)

    segment_counts = out["segment_key"].value_counts().to_dict()

    # Final fallback when area buckets are still too sparse.
    low_segment_mask = out["segment_key"].map(segment_counts).fillna(0).astype(int) < cfg.min_segment_n
    out.loc[low_segment_mask, "segment_key"] = "county:COUNTYWIDE"

    segment_counts = out["segment_key"].value_counts().to_dict()

    hood_map_rows: List[Dict[str, Any]] = []
    grouped = out.groupby("hood_code", dropna=False)
    for hood_code, hood_df in grouped:
        if hood_code == "":
            continue
        assigned_segment = str(hood_df["segment_key"].mode().iloc[0])
        hood_map_rows.append(
            {
                "hood_code": hood_code,
                "n_sales": int(len(hood_df)),
                "valuation_area": str(hood_df["valuation_area"].mode().iloc[0]),
                "geo_bucket": str(hood_df["geo_bucket"].mode().iloc[0]),
                "is_east_macro": bool(hood_df["is_east_macro"].mode().iloc[0]),
                "assigned_segment": assigned_segment,
            }
        )

    hood_map_rows.sort(key=lambda item: (-item["n_sales"], item["hood_code"]))
    return SegmentAssignment(frame=out, hood_map=hood_map_rows, segment_counts=segment_counts)


def _weighted_prd(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    ratio = df["ratio_calibrated"]
    mean_ratio = ratio.mean()
    weighted_mean = df["sale_price"].sum() / df["predicted_value"].sum() if df["predicted_value"].sum() else np.nan
    if pd.isna(weighted_mean) or weighted_mean == 0:
        return None
    return float(mean_ratio / weighted_mean)


def _compute_prb(df: pd.DataFrame) -> Optional[float]:
    if len(df) < 30:
        return None
    med_ratio = df["ratio_calibrated"].median()
    med_pred = df["predicted_value"].median()
    if med_ratio <= 0 or med_pred <= 0:
        return None

    y = (df["ratio_calibrated"] / med_ratio) - 1.0
    x = (df["predicted_value"] / med_pred) - 1.0
    mask = y.notna() & x.notna()
    if int(mask.sum()) < 20:
        return None

    try:
        model = sm.OLS(y[mask], sm.add_constant(x[mask])).fit()
        if len(model.params) < 2:
            return None
        return float(model.params.iloc[1])
    except Exception:
        return None


def _fit_single_segment(seg_df: pd.DataFrame, cfg: RegressionSettings, predictor_cols: List[str], holdout_cutoff: pd.Timestamp) -> Optional[SegmentModelResult]:
    if seg_df.empty:
        return None

    local = seg_df.copy()
    local["is_train"] = local["sale_date"] < holdout_cutoff
    local["is_validate"] = ~local["is_train"]

    train = local[local["is_train"]].copy()
    if train.empty:
        train = local.copy()
        local["is_train"] = True
        local["is_validate"] = False

    stage1 = train[
        train["raw_ratio"].between(cfg.ratio_min, cfg.ratio_max)
        & train["raw_ratio"].notna()
    ].copy()

    if len(stage1) < max(20, len(predictor_cols) + 5):
        return None

    active_predictors = [col for col in predictor_cols if col in stage1.columns and stage1[col].nunique() > 1]
    if not active_predictors:
        return None

    X_stage1 = sm.add_constant(stage1[active_predictors])
    y_stage1 = np.log(stage1["sale_price"])

    try:
        model_stage1 = sm.OLS(y_stage1, X_stage1).fit(cov_type="HC3")
    except Exception:
        return None

    stage1["pred_initial"] = np.exp(model_stage1.predict(X_stage1))
    stage1["ratio_initial"] = stage1["sale_price"] / stage1["pred_initial"]

    influence = OLSInfluence(model_stage1)
    stage1["studentized_residual"] = influence.resid_studentized_external

    q1 = float(stage1["ratio_initial"].quantile(0.25))
    q3 = float(stage1["ratio_initial"].quantile(0.75))
    iqr = q3 - q1
    iqr_min = q1 - (cfg.iqr_multiplier * iqr)
    iqr_max = q3 + (cfg.iqr_multiplier * iqr)

    residual_mask = stage1["studentized_residual"].abs() <= cfg.residual_z_max
    iqr_mask = stage1["ratio_initial"].between(iqr_min, iqr_max)
    final_mask = residual_mask & iqr_mask
    stage2 = stage1[final_mask].copy()

    if len(stage2) < max(20, len(active_predictors) + 5):
        return None

    X_stage2 = sm.add_constant(stage2[active_predictors])
    y_stage2 = np.log(stage2["sale_price"])

    try:
        model_final = sm.OLS(y_stage2, X_stage2).fit(cov_type="HC3")
    except Exception:
        return None

    model_cols = ["const"] + active_predictors

    stage1_filter_all = local[
        local["raw_ratio"].between(cfg.ratio_min, cfg.ratio_max)
        & local["raw_ratio"].notna()
    ].copy()
    if stage1_filter_all.empty:
        return None

    X_all = sm.add_constant(stage1_filter_all[active_predictors])
    stage1_filter_all["predicted_value"] = np.exp(model_final.predict(X_all))
    stage1_filter_all["ratio_raw"] = stage1_filter_all["sale_price"] / stage1_filter_all["predicted_value"]

    median_ratio = float(stage1_filter_all["ratio_raw"].median()) if not stage1_filter_all.empty else 1.0
    if median_ratio <= 0 or not math.isfinite(median_ratio):
        median_ratio = 1.0
    segment_scalar = 1.0 / median_ratio

    stage1_filter_all["ratio_calibrated"] = stage1_filter_all["ratio_raw"] * segment_scalar

    neighborhood_scalars: Dict[str, float] = {}
    if cfg.enable_neighborhood_scalars:
        hood_groups = stage1_filter_all.groupby("hood_code")
        for hood, hood_df in hood_groups:
            if not hood or len(hood_df) < 15:
                continue
            hood_med = float(hood_df["ratio_raw"].median())
            if hood_med <= 0 or not math.isfinite(hood_med):
                continue
            neighborhood_scalars[str(hood)] = float(np.clip(1.0 / hood_med, 0.75, 1.25))

    cod = float(
        (
            (stage1_filter_all["ratio_calibrated"] - stage1_filter_all["ratio_calibrated"].median()).abs()
            / stage1_filter_all["ratio_calibrated"].median()
        ).median()
        * 100
    )
    prd = _weighted_prd(stage1_filter_all)
    prb = _compute_prb(stage1_filter_all)

    residuals = model_final.resid
    rmse = float(np.sqrt(np.mean(np.square(residuals)))) if len(residuals) else None

    validate_df = stage1_filter_all[stage1_filter_all["is_validate"]].copy()
    validate_rmse = None
    if not validate_df.empty:
        validate_rmse = float(
            np.sqrt(np.mean(np.square(np.log(validate_df["sale_price"]) - np.log(validate_df["predicted_value"]))))
        )

    coeffs = {
        key: float(value)
        for key, value in model_final.params.items()
        if key in model_cols
    }
    coef_se = {
        key: float(value)
        for key, value in model_final.bse.items()
        if key in model_cols
    }

    valuation_area_mode = str(seg_df["valuation_area"].mode().iloc[0]) if seg_df["valuation_area"].notna().any() else "OTHER"

    outlier_counts = {
        "stage1_ratio_excluded": int(len(train) - len(stage1)),
        "stage2_residual_excluded": int((~residual_mask).sum()),
        "stage2_iqr_excluded": int((~iqr_mask).sum()),
        "stage2_total_excluded": int(len(stage1) - len(stage2)),
    }

    metrics = {
        "n": int(len(stage1_filter_all)),
        "n_train": int(local["is_train"].sum()),
        "n_validate": int(local["is_validate"].sum()),
        "r2": float(model_final.rsquared),
        "adj_r2": float(model_final.rsquared_adj),
        "rmse": rmse,
        "cod": float(cod),
        "prd": float(prd) if prd is not None else None,
        "prb": float(prb) if prb is not None else None,
        "median_ratio": float(stage1_filter_all["ratio_calibrated"].median()),
        "validation_rmse": validate_rmse,
    }

    return SegmentModelResult(
        segment_key=str(seg_df["segment_key"].iloc[0]),
        valuation_area=valuation_area_mode,
        n_total=int(len(seg_df)),
        n_train=int(local["is_train"].sum()),
        n_validate=int(local["is_validate"].sum()),
        n_fit=int(len(stage2)),
        predictors=active_predictors,
        coefficients=coeffs,
        coefficient_se=coef_se,
        segment_scalar=float(segment_scalar),
        neighborhood_scalars=neighborhood_scalars,
        metrics=metrics,
        outlier_counts=outlier_counts,
    )


def run_regression(cfg: RegressionSettings, run_id: str) -> RegressionRunResult:
    sales_df = _load_sales_frame()
    if sales_df.empty:
        raise ValueError("No sales found for regression_v1 dataset")

    sales_df = _apply_training_window(sales_df, cfg)
    if sales_df.empty:
        raise ValueError("No sales found after applying training window")

    anchor_date = _resolve_anchor_date(sales_df, cfg)
    cfg.anchor_date = anchor_date.isoformat()

    featured_df = _build_features(sales_df, cfg, anchor_date)
    hood_lon_map = _load_hood_longitudes()
    assignment = assign_segments(featured_df, cfg, hood_lon_map)

    run_frame = assignment.frame.copy()
    holdout_cutoff = run_frame["sale_date"].max() - pd.DateOffset(months=12)

    predictor_cols = [col for col in cfg.predictors if col in run_frame.columns]
    predictor_cols.extend([term for term in cfg.interaction_terms if term in run_frame.columns and term not in predictor_cols])

    segment_results: List[SegmentModelResult] = []
    for segment_key, seg_df in run_frame.groupby("segment_key"):
        if len(seg_df) < cfg.min_segment_n:
            continue
        result = _fit_single_segment(seg_df.copy(), cfg, predictor_cols, holdout_cutoff)
        if result:
            segment_results.append(result)

    if not segment_results:
        raise ValueError("No segment models could be fit for regression_v1")

    segment_summary: List[Dict[str, Any]] = []
    coefficients: List[Dict[str, Any]] = []

    total_observations = 0
    weighted_cod = 0.0
    weighted_prd = 0.0
    weighted_prb = 0.0
    weighted_r2 = 0.0
    weighted_rmse = 0.0
    prd_weight = 0
    prb_weight = 0
    rmse_weight = 0

    for result in segment_results:
        n = int(result.metrics.get("n", 0))
        total_observations += n

        cod_val = result.metrics.get("cod")
        if cod_val is not None:
            weighted_cod += float(cod_val) * n

        prd_val = result.metrics.get("prd")
        if prd_val is not None:
            weighted_prd += float(prd_val) * n
            prd_weight += n

        prb_val = result.metrics.get("prb")
        if prb_val is not None:
            weighted_prb += float(prb_val) * n
            prb_weight += n

        r2_val = result.metrics.get("r2")
        if r2_val is not None:
            weighted_r2 += float(r2_val) * n

        rmse_val = result.metrics.get("rmse")
        if rmse_val is not None:
            weighted_rmse += float(rmse_val) * n
            rmse_weight += n

        segment_summary.append(
            {
                "segment_key": result.segment_key,
                "valuation_area": result.valuation_area,
                "n_total": result.n_total,
                "n_train": result.n_train,
                "n_validate": result.n_validate,
                "n_fit": result.n_fit,
                "predictors": result.predictors,
                "segment_scalar": result.segment_scalar,
                "neighborhood_scalars": result.neighborhood_scalars,
                "metrics": result.metrics,
                "outlier_counts": result.outlier_counts,
            }
        )

        coefficients.append(
            {
                "segment_key": result.segment_key,
                "coefficients": [
                    {
                        "term": term,
                        "beta": result.coefficients.get(term),
                        "beta_se": result.coefficient_se.get(term),
                    }
                    for term in ["const"] + result.predictors
                    if term in result.coefficients
                ],
            }
        )

    total_segments = len(segment_summary)
    global_metrics = {
        "total_observations": int(total_observations),
        "segments": int(total_segments),
        "cod": float(weighted_cod / total_observations) if total_observations else None,
        "prd": float(weighted_prd / prd_weight) if prd_weight else None,
        "prb": float(weighted_prb / prb_weight) if prb_weight else None,
        "r2": float(weighted_r2 / total_observations) if total_observations else None,
        "rmse": float(weighted_rmse / rmse_weight) if rmse_weight else None,
        "market_groups": sorted({row["valuation_area"] for row in segment_summary}),
    }

    payload = {
        "metadata": {
            "run_id": run_id,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "model_version": "regression_v1",
            "mode": cfg.mode,
            "anchor_date": cfg.anchor_date,
            "holdout_cutoff": str(holdout_cutoff.date()),
        },
        "settings": cfg.to_dict(),
        "segment_summary": segment_summary,
        "global_metrics": global_metrics,
        "coefficients": coefficients,
        "segment_map": assignment.hood_map,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    diagnostics_path = RUNS_DIR / f"{run_id}.json"
    diagnostics_path.write_text(json.dumps(payload, indent=2, default=str))

    return RegressionRunResult(
        run_id=run_id,
        status="completed",
        settings=cfg.to_dict(),
        segment_summary=segment_summary,
        global_metrics=global_metrics,
        diagnostics_path=str(diagnostics_path),
        coefficients=coefficients,
        segment_map=assignment.hood_map,
    )


def load_run_payload(run_id: str) -> Optional[Dict[str, Any]]:
    target = RUNS_DIR / f"{run_id}.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except json.JSONDecodeError:
        return None


def _extract_parcel_features(parcel_row: Dict[str, Any], cfg: RegressionSettings, anchor_date: dt.date) -> Dict[str, float]:
    living_area = float(parcel_row.get("living_area") or 0.0)
    lot_acres = float(parcel_row.get("lot_acres") or 0.0)
    year_built = float(parcel_row.get("year_built") or anchor_date.year)
    quality = float(parcel_row.get("quality_score") or 0.0)
    condition = float(parcel_row.get("condition_score") or 0.0)
    bedrooms = float(parcel_row.get("bedrooms") or 0.0)
    bathrooms = float(parcel_row.get("bathrooms") or 0.0)
    has_garage = float(parcel_row.get("has_garage") or 0.0)
    has_basement = float(parcel_row.get("has_basement") or 0.0)
    total_market_value = float(parcel_row.get("total_market_value") or 0.0)
    land_market_value = float(parcel_row.get("land_market_value") or 0.0)

    age = max(0.0, float(anchor_date.year - year_built))
    land_share = 0.0
    if total_market_value > 0:
        land_share = min(1.0, max(0.0, land_market_value / total_market_value))

    base = {
        "log_area": float(np.log(max(living_area, 1.0))),
        "log_lot": float(np.log1p(max(lot_acres, 0.0))),
        "log_age": float(np.log1p(max(age, 0.0))),
        "quality_score": quality,
        "condition_score": condition,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "has_garage": has_garage,
        "has_basement": has_basement,
        "land_share": land_share,
        "months_to_anchor": 0.0,
    }

    for term in cfg.interaction_terms:
        definition = INTERACTION_DEFINITIONS.get(term)
        if definition is None:
            continue
        left, right = definition
        base[term] = float(base.get(left, 0.0) * base.get(right, 0.0))

    return base


def _load_parcel_row(parcel_number: str) -> Optional[Dict[str, Any]]:
    sql = """
    SELECT
      mp.parcel_number,
      mp.hood_code,
      mp.total_market_value::double precision AS total_market_value,
      (COALESCE(mp.impr_land_value, 0) + COALESCE(mp.unimpr_land_value, 0))::double precision AS land_market_value,
      COALESCE(mp.final_living_area, mp.total_living_area, mp.living_area)::double precision AS living_area,
      COALESCE(mp.acres, 0)::double precision AS lot_acres,
      COALESCE(mp.final_year_built, mp.year_built, mp.year_built_max)::double precision AS year_built,
      COALESCE(mp.quality_score, 0)::double precision AS quality_score,
      COALESCE(mp.condition_score, 0)::double precision AS condition_score,
      COALESCE(mp.number_of_bedrooms, 0)::double precision AS bedrooms,
      COALESCE(mp.total_baths, 0)::double precision AS bathrooms,
      CASE WHEN COALESCE(mp.final_garage_area, mp.total_garage_area, 0) > 0 THEN 1.0 ELSE 0.0 END AS has_garage,
      CASE
        WHEN COALESCE(mp.total_basement_area, 0) > 0
          OR COALESCE(mp.finishedbasement, 0) > 0
          OR COALESCE(mp.unfinishedbasement, 0) > 0
        THEN 1.0 ELSE 0.0
      END AS has_basement
    FROM master_parcel mp
    WHERE mp.parcel_number = %s
    LIMIT 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [parcel_number])
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [col[0] for col in cursor.description]
        return dict(zip(cols, row))


def predict_from_published_payload(
    payload: Dict[str, Any],
    parcel_number: str,
    anchor_date_override: Optional[dt.date] = None,
) -> Dict[str, Any]:
    settings_obj = parse_settings(payload.get("settings") or {})
    model_anchor = dt.date.fromisoformat(settings_obj.anchor_date) if settings_obj.anchor_date else dt.date.today()
    anchor_date = anchor_date_override or model_anchor

    parcel_row = _load_parcel_row(parcel_number)
    if parcel_row is None:
        raise ValueError("Parcel not found")

    hood_code = str(parcel_row.get("hood_code") or "")
    valuation_area = _map_valuation_area(hood_code)

    hood_lon_map = _load_hood_longitudes()
    lon = hood_lon_map.get(hood_code)
    geo_bucket = _geo_bucket(lon, settings_obj)
    is_east_macro = _is_east_macro(valuation_area, geo_bucket, hood_code)

    segment_map_rows = payload.get("segment_map") or []
    hood_segment_map = {
        str(row.get("hood_code")): str(row.get("assigned_segment"))
        for row in segment_map_rows
        if row.get("hood_code") and row.get("assigned_segment")
    }

    segment_key = hood_segment_map.get(hood_code)
    if not segment_key:
        if is_east_macro:
            segment_key = "macro:EAST_COUNTY"
        else:
            segment_key = f"area:{valuation_area}"

    segment_summary = payload.get("segment_summary") or []
    segment_by_key = {
        str(row.get("segment_key")): row
        for row in segment_summary
        if row.get("segment_key")
    }

    if segment_key not in segment_by_key:
        area_segment = f"area:{valuation_area}"
        if area_segment in segment_by_key:
            segment_key = area_segment
        elif "county:COUNTYWIDE" in segment_by_key:
            segment_key = "county:COUNTYWIDE"
        elif segment_by_key:
            segment_key = sorted(segment_by_key.keys())[0]
        else:
            raise ValueError("No segments available in published model")

    coef_groups = payload.get("coefficients") or []
    coef_map_by_segment: Dict[str, Dict[str, float]] = {}
    for group in coef_groups:
        group_key = str(group.get("segment_key") or "")
        rows = group.get("coefficients") or []
        coef_map_by_segment[group_key] = {
            str(item.get("term")): float(item.get("beta", 0.0))
            for item in rows
            if item.get("term") is not None
        }

    segment_coeffs = coef_map_by_segment.get(segment_key)
    if not segment_coeffs:
        raise ValueError(f"No coefficients found for segment {segment_key}")

    features = _extract_parcel_features(parcel_row, settings_obj, anchor_date)

    pred_ln = float(segment_coeffs.get("const", 0.0))
    for term, beta in segment_coeffs.items():
        if term == "const":
            continue
        pred_ln += float(beta) * float(features.get(term, 0.0))

    predicted_value = float(math.exp(pred_ln))

    seg_payload = segment_by_key.get(segment_key, {})
    seg_scalar = float(seg_payload.get("segment_scalar") or 1.0)

    hood_scalars = seg_payload.get("neighborhood_scalars") or {}
    hood_scalar = float(hood_scalars.get(hood_code, 1.0)) if isinstance(hood_scalars, dict) else 1.0

    adjusted_value = predicted_value * seg_scalar * hood_scalar

    metrics = seg_payload.get("metrics") or {}
    rmse = metrics.get("rmse")
    confidence_band = None
    if rmse is not None:
        rmse_val = float(rmse)
        confidence_band = {
            "lower": float(adjusted_value * math.exp(-1.96 * rmse_val)),
            "upper": float(adjusted_value * math.exp(1.96 * rmse_val)),
        }

    return {
        "parcel_number": parcel_number,
        "anchor_date": anchor_date.isoformat(),
        "segment_key": segment_key,
        "valuation_area": valuation_area,
        "geo_bucket": geo_bucket,
        "predicted_value": adjusted_value,
        "base_predicted_value": predicted_value,
        "segment_scalar": seg_scalar,
        "neighborhood_scalar": hood_scalar,
        "confidence_band": confidence_band,
    }
