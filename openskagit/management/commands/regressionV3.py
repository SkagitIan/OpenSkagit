import datetime
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from openskagit.models import AdjustmentCoefficient, AdjustmentRunSummary


# ============================================================
# GLOBAL CONFIG
# ============================================================

ANCHOR_DATE = pd.Timestamp("2015-01-01")

# Core predictors that form the backbone of the model
CORE_PREDICTORS: List[str] = [
    "log_area",
    "log_lot",
    "log_age",
    "t",              # may be swapped against area_time by family rules
    "quality_score",
    "condition_score",
    "has_garage",
    "has_basement",
    "is_view",
]

# Extra predictors that can be selected if they help
# Note: value_time is intentionally excluded – highly collinear
CANDIDATE_PREDICTORS: List[str] = [
    # land & value structure
    "land_share",
    "log_land_value",

    # interactions and time structure
    "area_time",
    "area_quality",
    "area_condition",

    # terrain / flood / distance / shape
    "elev_log",
    "slope_log",
    "slope_sq",
    "aspect_sin",
    "aspect_cos",
    "dist_major_road_log",
    "dist_floodway_log",
    "flood_distance_log",
    "flood_influence",
    "compactness_log",
    "far",
]

# Terrain terms we treat as a family and restrict to best 1–2 per segment
TERRAIN_TERMS: List[str] = [
    "elev_log",
    "slope_log",
    "slope_sq",
    "aspect_sin",
    "aspect_cos",
    "dist_major_road_log",
    "flood_distance_log",
    "dist_floodway_log",
    "compactness_log",
]

# Terms we do NOT automatically drop in VIF pruning
PROTECTED_TERMS: List[str] = [
    "log_area",
    "log_lot",
    "log_age",
    "t",
    "area_time",
    "quality_score",
]

# Predictor families
LAND_FAMILY = {"log_lot", "land_share", "log_land_value"}
QUALITY_FAMILY = {"quality_score", "condition_score", "area_quality", "area_condition"}
TIME_FAMILY = {"t", "area_time"}  # choice C: auto strategy per segment

# ============================================================
# STAT HELPERS
# ============================================================

def stepwise_aic_selection(
    X: pd.DataFrame,
    y: pd.Series,
    core: Sequence[str],
    candidates: Sequence[str],
    max_steps: int = 25,
) -> List[str]:
    """
    Forward stepwise selection using AIC.
    Core variables are forced in; candidates only added if AIC improves.
    """
    selected = [c for c in core if c in X.columns]
    remaining = [c for c in candidates if c in X.columns and c not in selected]

    if selected:
        base_X = sm.add_constant(X[selected])
        base_model = sm.OLS(y, base_X).fit(cov_type="HC3")
        best_aic = base_model.aic
    else:
        best_aic = np.inf

    for _ in range(max_steps):
        best_candidate = None
        best_candidate_aic = best_aic

        for cand in list(remaining):
            cols = selected + [cand]
            try:
                tmp_model = sm.OLS(y, sm.add_constant(X[cols])).fit(cov_type="HC3")
                cand_aic = tmp_model.aic
            except Exception:
                continue

            if cand_aic + 1e-6 < best_candidate_aic:
                best_candidate_aic = cand_aic
                best_candidate = cand

        if best_candidate is None:
            break

        selected.append(best_candidate)
        remaining.remove(best_candidate)
        best_aic = best_candidate_aic

    return selected


def compute_cod_prd(
    sale_price: pd.Series,
    pred_price: pd.Series,
) -> Tuple[float, float, float]:
    """
    Compute IAAO COD and PRD, plus median ratio.
    """
    ratio = sale_price / pred_price.replace(0, np.nan)
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()

    if ratio.empty:
        return np.nan, np.nan, np.nan

    med = ratio.median()
    cod = (ratio.sub(med).abs() / med).median() * 100.0

    low = ratio[ratio < med]
    high = ratio[ratio >= med]

    if len(low) > 0 and len(high) > 0:
        prd = high.mean() / low.mean()
    else:
        prd = np.nan

    return float(cod), float(prd), float(med)


def compute_prb_safe(
    sale_price: pd.Series,
    pred_price: pd.Series,
) -> Optional[float]:
    """
    Curvature-safe PRB estimator.

    Uses:
      y = ratio - median_ratio
      x = pred^(1/3) - median(pred^(1/3))

    Returns slope of OLS(y ~ x) or None if unstable.
    """
    df = pd.DataFrame({"sale_price": sale_price, "pred": pred_price}).copy()
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 50:
        return None

    ratio = df["sale_price"] / df["pred"].replace(0, np.nan)
    ratio = ratio.replace([np.inf, -np.inf], np.nan)
    df = df.assign(ratio=ratio).dropna()
    if len(df) < 50:
        return None

    median_ratio = df["ratio"].median()
    y = df["ratio"] - median_ratio

    px_cubert = df["pred"].pow(1.0 / 3.0)
    x = px_cubert - px_cubert.median()

    if x.std() < 1e-9:
        return None

    try:
        X = sm.add_constant(x)
        model = sm.OLS(y, X).fit()
        slope = float(model.params.iloc[1])
    except Exception:
        return None

    return slope


def compute_vif_table(X: pd.DataFrame) -> Dict[str, float]:
    """
    Compute VIF for each predictor (excluding constant).
    Returns {term: vif_value}.
    """
    if X.shape[1] == 0:
        return {}

    vif_results: Dict[str, float] = {}
    cols = list(X.columns)
    X_vals = X.values.astype(float)

    for i, col in enumerate(cols):
        try:
            vif = float(variance_inflation_factor(X_vals, i))
        except Exception:
            vif = float("nan")
        vif_results[col] = vif

    return vif_results


# ============================================================
# MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):
    help = "Regression v4: area × value-tier segments, geo features, VIF pruning, and robust PRB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--market-group-col",
            type=str,
            default="valuation_area",
            help="Column name used to define market groups (default: valuation_area).",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="Optional run ID; if omitted, uses current timestamp.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without writing results to the database.",
        )
        parser.add_argument(
            "--undo",
            action="store_true",
            help="Delete a previous run (requires --run-id).",
        )
        parser.add_argument(
            "--countywide",
            action="store_true",
            help="Ignore market-group column and run a single countywide model.",
        )

    # -------------------------------------------------------
    # Undo previous run
    # -------------------------------------------------------
    def handle_undo(self, run_id: Optional[str]) -> None:
        if not run_id:
            self.stdout.write(self.style.ERROR("You must supply --run-id with --undo."))
            return

        with transaction.atomic():
            coef_deleted = AdjustmentCoefficient.objects.filter(run_id=run_id).delete()
            summary_deleted = AdjustmentRunSummary.objects.filter(run_id=run_id).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted coefficients={coef_deleted[0]}, summaries={summary_deleted[0]} for run_id={run_id}"
            )
        )

    # -------------------------------------------------------
    # Feature engineering
    # -------------------------------------------------------
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all feature transformations:
        - size / age / time
        - land & value composition
        - geo / terrain / flood / distance / shape
        - interactions
        - log_price target
        """
        df = df.copy()

        # Core size / age
        df["log_area"] = np.log(df["living_area"].clip(lower=1))
        df["log_lot"] = np.log1p(df["lot_acres"].clip(lower=0))

        if "age" not in df.columns:
            if "age_raw" in df.columns:
                df["age"] = df["age_raw"]
            elif "year_built" in df.columns:
                df["age"] = np.where(
                    df["year_built"].notna(),
                    2025 - df["year_built"],
                    np.nan,
                )
            else:
                df["age"] = np.nan

        df["age"] = df["age"].clip(lower=0)
        df["log_age"] = np.log1p(df["age"])
        df["log_area_sq"] = df["log_area"] ** 2

        # Time index
        df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
        df = df[df["sale_date"].notna()]
        df["t"] = (df["sale_date"] - ANCHOR_DATE).dt.days / 30.4375
        df["t_sq"] = df["t"] ** 2

        # Land & assessor value features
        df["log_land_value"] = np.log1p(df["land_market_value"].clip(lower=0))
        df["log_total_mv"] = np.log1p(df["total_market_value"].clip(lower=0))
        df["log_total_mv_sq"] = df["log_total_mv"] ** 2

        with np.errstate(divide="ignore", invalid="ignore"):
            land_share = df["land_market_value"] / df["total_market_value"].replace(0, np.nan)
        df["land_share"] = land_share.clip(lower=0, upper=1).fillna(0)
        df["land_time"] = df["land_share"] * df["t"]

        # Terrain: elevation / slope
        if "elevation" in df.columns:
            df["elevation"] = df["elevation"].fillna(0)
        elif "elev" in df.columns:
            df["elevation"] = df["elev"].fillna(0)
        else:
            df["elevation"] = 0.0

        df["slope"] = df.get("slope", np.nan).fillna(0)

        df["elev_log"] = np.log1p(df["elevation"].clip(lower=0))
        df["slope_log"] = np.log1p(df["slope"].clip(lower=0))
        df["slope_sq"] = df["slope"] ** 2

        # Aspect → sin/cos
        df["aspect"] = df.get("aspect", np.nan).fillna(0)
        radians = np.deg2rad(df["aspect"])
        df["aspect_sin"] = np.sin(radians)
        df["aspect_cos"] = np.cos(radians)

        # Flood-related
        df["flood_influence"] = df.get("flood_influence", 0).fillna(0)
        df["flood_distance"] = df.get("flood_distance", np.nan)
        df["dist_floodway"] = df.get("dist_floodway", np.nan)
        df["flood_depth"] = df.get("flood_depth", 0).fillna(0)
        df["flood_static_bfe"] = df.get("flood_static_bfe", 0).fillna(0)

        df["flood_distance_log"] = np.log1p(df["flood_distance"].clip(lower=0))
        df["dist_floodway_log"] = np.log1p(df["dist_floodway"].clip(lower=0))

        # Distance to major road
        df["dist_major_road"] = df.get("dist_major_road", np.nan)
        df["dist_major_road_log"] = np.log1p(df["dist_major_road"].clip(lower=0))

        # Shape / intensity
        df["parcel_compactness"] = df.get("parcel_compactness", np.nan)
        df["compactness_log"] = np.log1p(df["parcel_compactness"].clip(lower=0))

        df["floor_area_ratio"] = df.get("floor_area_ratio", np.nan)
        df["far"] = df["floor_area_ratio"].fillna(0)

        # Quality / condition / amenity flags
        df["missing_quality"] = df["quality_score"].isna().astype(int)
        df["missing_condition"] = df["condition_score"].isna().astype(int)
        df["quality_score"] = df["quality_score"].fillna(df["quality_score"].median())
        df["condition_score"] = df["condition_score"].fillna(df["condition_score"].median())

        df["has_garage"] = df.get("has_garage", 0).fillna(0).astype(int)
        df["has_basement"] = df.get("has_basement", 0).fillna(0).astype(int)
        df["is_view"] = df.get("is_view", 0).fillna(0).astype(int)

        # Interactions
        df["area_time"] = df["log_area"] * df["t"]
        df["area_quality"] = df["log_area"] * df["quality_score"]
        df["area_condition"] = df["log_area"] * df["condition_score"]

        # Target
        df["log_price"] = np.log(df["sale_price"].clip(lower=1))

        # Clean infinities
        df = df.replace([np.inf, -np.inf], np.nan)

        return df

    # -------------------------------------------------------
    # Price tier dummies (for PRD/curvature in model)
    # -------------------------------------------------------
    def add_price_tiers(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        try:
            df["price_tier"] = pd.qcut(
                df["sale_price"],
                5,
                labels=False,
                duplicates="drop",
            )
        except ValueError:
            df["price_tier"] = pd.cut(
                df["sale_price"].rank(method="first"),
                bins=5,
                labels=False,
            )

        df["price_tier"] = df["price_tier"].astype(float)
        pt_dummies = pd.get_dummies(
            df["price_tier"], prefix="pt", drop_first=True, dtype=float
        )
        df = df.join(pt_dummies)
        return df

    # -------------------------------------------------------
    # Family rules + terrain selection
    # -------------------------------------------------------
    def apply_family_rules(
        self,
        selected: List[str],
        model: sm.regression.linear_model.RegressionResultsWrapper,
        segment_size: int,
    ) -> Tuple[List[str], Dict[str, Any]]:
        dropped_for_families: List[str] = []
        selected_set = set(selected)

        # LAND FAMILY: keep priority log_lot > land_share > log_land_value
        land_terms = selected_set & LAND_FAMILY
        if land_terms:
            keep = None
            for cand in ["log_lot", "land_share", "log_land_value"]:
                if cand in land_terms:
                    keep = cand
                    break
            for term in land_terms:
                if term != keep:
                    selected_set.remove(term)
                    dropped_for_families.append(term)

        # QUALITY FAMILY: limit to one interaction; prefer area_quality
        interaction_terms = {"area_quality", "area_condition"}
        qi = selected_set & interaction_terms
        if len(qi) > 1:
            if "area_quality" in qi:
                keep_int = "area_quality"
            else:
                keep_int = sorted(qi)[0]
            for term in qi:
                if term != keep_int:
                    selected_set.remove(term)
                    dropped_for_families.append(term)

        # TIME FAMILY, strategy C: auto choice
        # If both t and area_time selected:
        #   - if segment_size >= 1000 → prefer area_time
        #   - else → prefer t
        time_terms = selected_set & TIME_FAMILY
        if len(time_terms) > 1:
            if segment_size >= 1000:
                drop_term = "t"
            else:
                drop_term = "area_time"
            if drop_term in selected_set:
                selected_set.remove(drop_term)
                dropped_for_families.append(drop_term)

        # TERRAIN FAMILY: keep at most 2 by |t-stat|
        terrain_terms = selected_set & set(TERRAIN_TERMS)
        if terrain_terms:
            term_stats = []
            for term in terrain_terms:
                if term in model.params.index and term in model.tvalues.index:
                    tval = float(model.tvalues[term])
                    term_stats.append((term, abs(tval)))
                else:
                    term_stats.append((term, 0.0))

            term_stats.sort(key=lambda x: x[1], reverse=True)
            keep_terrain = [t for t, _ in term_stats[:2]]

            for term, _tval in term_stats[2:]:
                if term in selected_set:
                    selected_set.remove(term)
                    dropped_for_families.append(term)

        return list(selected_set), {
            "dropped_for_families": dropped_for_families,
        }

    # -------------------------------------------------------
    # VIF pruning
    # -------------------------------------------------------
    def vif_prune(
        self,
        X_full: pd.DataFrame,
        y: pd.Series,
        selected: List[str],
        max_vif: float = 10.0,
    ) -> Tuple[List[str], Dict[str, Any], Optional[sm.regression.linear_model.RegressionResultsWrapper]]:
        dropped_for_vif: List[str] = []
        cur_selected = list(selected)

        if not cur_selected:
            return cur_selected, {
                "dropped_for_vif": dropped_for_vif,
                "vif_before": {},
                "vif_after": {},
            }, None

        X = sm.add_constant(X_full[cur_selected])
        model = sm.OLS(y, X).fit(cov_type="HC3")
        vif_before = compute_vif_table(X_full[cur_selected])

        while True:
            vif_dict = compute_vif_table(X_full[cur_selected])
            offenders = {term: v for term, v in vif_dict.items() if v == v and v > max_vif}
            if not offenders:
                break

            sorted_offenders = sorted(offenders.items(), key=lambda x: x[1], reverse=True)
            drop_term = None
            for term, _v in sorted_offenders:
                if term not in PROTECTED_TERMS:
                    drop_term = term
                    break

            if drop_term is None:
                break

            if drop_term not in cur_selected:
                break

            cur_selected.remove(drop_term)
            dropped_for_vif.append(drop_term)

            if not cur_selected:
                break

            X = sm.add_constant(X_full[cur_selected])
            model = sm.OLS(y, X).fit(cov_type="HC3")

        vif_after = compute_vif_table(X_full[cur_selected]) if cur_selected else {}

        meta = {
            "dropped_for_vif": dropped_for_vif,
            "vif_before": vif_before,
            "vif_after": vif_after,
        }
        return cur_selected, meta, model

    # -------------------------------------------------------
    # Run one segment model (area × value_tier)
    # -------------------------------------------------------
    def run_segment_model(
        self,
        subdf: pd.DataFrame,
        label: str,
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], sm.regression.linear_model.RegressionResultsWrapper]]:
        df = subdf.copy()

        # Basic filters
        df = df.dropna(subset=["sale_price", "living_area", "lot_acres"])
        df = df[df["sale_price"] > 50_000]

        if len(df) < 80:
            self.stdout.write(f"  [SKIP] {label}: too few sales ({len(df)})")
            return None

        # Trim tails: 5–95% on price, 1–99% on area/lot
        p_lo, p_hi = df["sale_price"].quantile([0.05, 0.95])
        a_lo, a_hi = df["living_area"].quantile([0.01, 0.99])
        l_lo, l_hi = df["lot_acres"].quantile([0.01, 0.99])

        df = df[
            df["sale_price"].between(p_lo, p_hi)
            & df["living_area"].between(a_lo, a_hi)
            & df["lot_acres"].between(l_lo, l_hi)
        ]

        if len(df) < 60:
            self.stdout.write(f"  [SKIP] {label}: too few after trimming ({len(df)})")
            return None

        # Add price tier dummies (separate from segment tier)
        df = self.add_price_tiers(df)

        y = df["log_price"]

        all_predictors: List[str] = list(set(CORE_PREDICTORS + CANDIDATE_PREDICTORS))
        pt_cols = [c for c in df.columns if c.startswith("pt_")]
        all_predictors.extend(pt_cols)

        available = [c for c in all_predictors if c in df.columns]

        X_full = df[available].replace([np.inf, -np.inf], np.nan).dropna()
        y = y.loc[X_full.index]

        if len(X_full) < 50:
            self.stdout.write(f"  [SKIP] {label}: not enough rows after NA cleanup ({len(X_full)})")
            return None

        # Phase 1: stepwise AIC
        selected_phase1 = stepwise_aic_selection(
            X_full,
            y,
            core=CORE_PREDICTORS,
            candidates=[c for c in available if c not in CORE_PREDICTORS],
        )

        if not selected_phase1:
            self.stdout.write(f"  [SKIP] {label}: no predictors selected in Phase 1.")
            return None

        X_phase1 = sm.add_constant(X_full[selected_phase1])
        model_phase1 = sm.OLS(y, X_phase1).fit(cov_type="HC3")
        vif_phase1 = compute_vif_table(X_full[selected_phase1])
        max_vif_phase1 = max((v for v in vif_phase1.values() if v == v), default=float("nan"))

        # Phase 2a: family rules + terrain
        selected_phase2, family_meta = self.apply_family_rules(
            selected_phase1,
            model_phase1,
            segment_size=len(df),
        )

        # Phase 2b: VIF pruning
        selected_final, vif_meta, model_final = self.vif_prune(
            X_full,
            y,
            selected_phase2,
            max_vif=10.0,
        )

        if not selected_final or model_final is None:
            self.stdout.write(f"  [SKIP] {label}: model collapsed after VIF pruning.")
            return None

        # Predictions
        X_final = sm.add_constant(X_full[selected_final])
        df_pred = df.loc[X_full.index].copy()
        df_pred["pred_ln"] = model_final.predict(X_final)
        smear = np.exp(model_final.resid).mean()
        df_pred["pred"] = np.exp(df_pred["pred_ln"]) * smear

        cod, prd, median_ratio = compute_cod_prd(
            df_pred["sale_price"],
            df_pred["pred"],
        )
        prb_val = compute_prb_safe(
            df_pred["sale_price"],
            df_pred["pred"],
        )

        stats: Dict[str, Any] = {
            "label": label,
            "valuation_area": str(df["valuation_area"].iloc[0]) if "valuation_area" in df.columns else None,
            "value_tier": str(df["value_tier"].iloc[0]) if "value_tier" in df.columns else None,
            "n": int(len(df_pred)),
            "r2": float(model_final.rsquared),
            "adj_r2": float(model_final.rsquared_adj),
            "COD": float(round(cod, 2)) if cod == cod else None,
            "PRD": float(round(prd, 3)) if prd == prd else None,
            "PRB": float(round(prb_val, 4)) if prb_val is not None else None,
            "median_ratio": float(round(median_ratio, 3)) if median_ratio == median_ratio else None,
            "price_min": float(df_pred["sale_price"].min()),
            "price_max": float(df_pred["sale_price"].max()),
            "variables": selected_final,
        }

        diagnostics = {
            "phase1": {
                "selected": selected_phase1,
                "vif": vif_phase1,
                "max_vif": max_vif_phase1,
            },
            "phase2": {
                "selected": selected_final,
                "family_drops": family_meta.get("dropped_for_families", []),
                "vif_before": vif_meta.get("vif_before", {}),
                "vif_after": vif_meta.get("vif_after", {}),
                "vif_drops": vif_meta.get("dropped_for_vif", []),
            },
        }

        return stats, diagnostics, model_final

    # -------------------------------------------------------
    # Main entry
    # -------------------------------------------------------
    def handle(self, *args, **options):
        if options.get("undo"):
            self.handle_undo(options.get("run_id"))
            return

        run_id = options.get("run_id") or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        mg_col = options.get("market_group_col") or "valuation_area"

        self.stdout.write(self.style.SUCCESS(f"Starting regression_v4 run {run_id} (group by: {mg_col} × value_tier)"))

        # Load from materialized view
        with connection.cursor():
            df = pd.read_sql_query("SELECT * FROM sale_regression_sfr", connection)

        # Base filters
        df = df.dropna(subset=["sale_price", "living_area"])
        df = df[df["sale_price"] > 10_000]

        # Features
        df = self.engineer_features(df)

        # Grouping choice
        if options.get("countywide"):
            groups = [("COUNTYWIDE", df)]
        else:
            if mg_col not in df.columns:
                raise ValueError(f"Grouping column '{mg_col}' not found in dataframe.")
            groups = list(df.groupby(mg_col))

        run_stats: List[Dict[str, Any]] = []
        coef_objects: List[AdjustmentCoefficient] = []
        diagnostics: Dict[str, Any] = {
            "model_version": "regression_v4",
            "run_id": run_id,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "market_group_col": mg_col,
            "segments": {},
        }

        for area_label, area_df in groups:
            area_str = str(area_label)
            self.stdout.write(self.style.SUCCESS(f"\n=== AREA: {area_str} ==="))

            # Value tier segmentation inside this area
            area_df = area_df.copy()
            try:
                area_df["value_tier"] = pd.qcut(
                    area_df["sale_price"],
                    q=[0, 0.33, 0.66, 1.0],
                    labels=["LOW", "MID", "HIGH"],
                    duplicates="drop",
                )
            except Exception:
                area_df["value_tier"] = "ALL"

            for tier_label, seg_df in area_df.groupby("value_tier"):
                tier_str = str(tier_label)
                segment_label = f"{area_str}__{tier_str}"
                self.stdout.write(self.style.SUCCESS(f"  SEGMENT: {segment_label}"))

                result = self.run_segment_model(seg_df, segment_label)
                if result is None:
                    continue

                stats, diag, model_final = result
                run_stats.append(stats)

                # Diagnostics entry
                diagnostics["segments"][segment_label] = {
                    "area": area_str,
                    "value_tier": tier_str,
                    "stats": stats,
                    "phase1": diag["phase1"],
                    "phase2": diag["phase2"],
                }

                # Build coefficients for this segment
                for term, beta in model_final.params.items():
                    coef_objects.append(
                        AdjustmentCoefficient(
                            market_group=segment_label,
                            term=term,
                            beta=float(beta),
                            beta_se=float(model_final.bse.get(term, 0.0)),
                            run_id=run_id,
                        )
                    )

                self.stdout.write(
                    f"    Done: n={stats['n']}, R²={stats['r2']:.3f}, "
                    f"COD={stats['COD']}, PRD={stats['PRD']}, PRB={stats['PRB']}"
                )

        if not run_stats:
            self.stdout.write(self.style.ERROR("No models were successfully fit. Nothing to save."))
            return

        # Save diagnostics JSON (one file per run)
        diag_filename = f"regression_v4_diagnostics_{run_id}.json"
        with open(diag_filename, "w") as f:
            json.dump(diagnostics, f, indent=2)
        self.stdout.write(self.style.SUCCESS(f"Diagnostics saved to {diag_filename}"))

        if options.get("dry_run"):
            self.stdout.write(self.style.WARNING("Dry run complete. No database writes performed."))
            return

        # Save to DB
        self.stdout.write("Saving results to database...")
        with transaction.atomic():
            AdjustmentRunSummary.objects.update_or_create(
                run_id=run_id,
                defaults={"stats": run_stats},
            )
            AdjustmentCoefficient.objects.filter(run_id=run_id).delete()
            AdjustmentCoefficient.objects.bulk_create(coef_objects, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"✅ regression_v4 run {run_id} complete and saved."))
