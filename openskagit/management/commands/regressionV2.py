import datetime
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.cluster import KMeans

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from openskagit.models import AdjustmentCoefficient, AdjustmentRunSummary  # Assuming your models are here

# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------
MIN_ROWS_FOR_TIERING = 350

TIER_TRIMS = {
    # Trims still based on Sale Price quantiles, but applied after tiering by Predicted Price
    "T1_LOW":   {"price": (0.05, 0.95), "area": (0.05, 0.95)},
    "T2_MID":   {"price": (0.05, 0.95), "area": (0.02, 0.98)},
    "T3_HIGH":  {"price": (0.05, 0.99), "area": (0.02, 0.98)},
    "ALL":      {"price": (0.05, 0.95), "area": (0.02, 0.98)},
}

# 1. CORE VARIABLES: Always included (IAAO / PRB-aware base spec)
CORE_PREDICTORS = [
    # size & age
    "log_area",
    "log_area_sq",
    "log_age",
    "land_time",

    # time
    "t",
    "t_sq",

    # value-level controls
    "log_total_mv",
    "log_total_mv_sq",

    # key interactions driving PRB
    "area_quality",     # log_area * quality_score
    "area_time",        # log_area * t
    "area_condition",
    # level controls
    "quality_score",
    "condition_score",
]

# 2. CANDIDATE VARIABLES: Stepwise selection tests these
CANDIDATE_PREDICTORS = [
    # site / land & value mix
    "log_lot",
    "land_share",
    "log_land_value",

    # amenities
    "has_garage",
    "has_basement",
    "is_view",

    # data quality flags
    "missing_quality",
    "missing_condition",

    # extra interactions that may help PRB without bloating every group
    "area_condition",   # log_area * condition_score
    "value_time",       # log_total_mv * t
]

# Predictors used JUST for tiering (richer than CORE_PREDICTORS)
# Predictors used JUST for tiering (richer than CORE_PREDICTORS)
TIERING_PREDICTORS = CORE_PREDICTORS + [
    "log_lot",
    "has_garage",
    "has_basement",
    "is_view",
    "land_share",
    "log_land_value",
    "missing_quality",
    "missing_condition",
]


class Command(BaseCommand):
    help = "Two-Pass Regression: Tiering by Predicted Value, then Stepwise Selection."

    def add_arguments(self, parser):
        parser.add_argument("--market-group-col", type=str, default="valuation_area")
        parser.add_argument("--run-id", type=str, default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--undo", action="store_true")
        parser.add_argument("--countywide", action="store_true")

    # --- UTILITY METHODS (Undo, Stepwise Selection) ---
    def handle_undo(self, run_id: str | None):
        """Deletes coefficients and summary for a specific run."""
        qs_coef = AdjustmentCoefficient.objects.all()
        qs_summ = AdjustmentRunSummary.objects.all()

        if run_id:
            target = run_id
        else:
            last = qs_summ.order_by("-created_at").first()
            if not last:
                self.stdout.write("No runs found to undo.")
                return
            target = last.run_id

        with transaction.atomic():
            c_cnt, _ = qs_coef.filter(run_id=target).delete()
            s_cnt, _ = qs_summ.filter(run_id=target).delete()

        self.stdout.write(self.style.WARNING(f"Undid Run {target}: Deleted {c_cnt} coefs, {s_cnt} summaries."))

    def select_predictors_stepwise(self, df: pd.DataFrame, y_col: str,
                                   mandatory: list, candidates: list):
        """Forward Stepwise Selection using AIC."""
        selected = list(mandatory)
        pool = [c for c in candidates if c not in selected and c in df.columns and df[c].nunique() > 1]
        y = df[y_col]

        X_base = sm.add_constant(df[selected])
        try:
            current_aic = sm.OLS(y, X_base).fit().aic
        except Exception:
            return selected

        improved = True
        while improved and pool:
            improved = False
            best_new_aic = current_aic
            best_candidate = None

            for cand in pool:
                try:
                    test_vars = selected + [cand]
                    X_test = sm.add_constant(df[test_vars])
                    model_test = sm.OLS(y, X_test).fit()
                    aic_test = model_test.aic

                    if aic_test < best_new_aic - 2.0:
                        best_new_aic = aic_test
                        best_candidate = cand
                except Exception:
                    continue

            if best_candidate:
                selected.append(best_candidate)
                pool.remove(best_candidate)
                current_aic = best_new_aic
                improved = True

        return selected

    # -------------------------------------------------------------------
    # LOGIC 1: FEATURE ENGINEERING
    # -------------------------------------------------------------------
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies feature transformations needed for both Pass 1 and Pass 2."""
        df["log_area"] = np.log(df["living_area"].clip(lower=1))
        df["log_lot"] = np.log1p(df["lot_acres"].clip(lower=0))
        df["log_age"] = np.log1p(df["age"].clip(lower=0))
        df["log_area_sq"] = df["log_area"] ** 2

        # Time Trend
        ANCHOR = pd.Timestamp("2015-01-01")
        df["t"] = (df["sale_date"] - ANCHOR).dt.days / 30.4375
        df["t_sq"] = df["t"] ** 2

        # Land & assessor value features
        df["log_land_value"] = np.log1p(df["land_market_value"].clip(lower=0))
        df["log_total_mv"] = np.log1p(df["total_market_value"].clip(lower=0))
        df["log_total_mv_sq"] = df["log_total_mv"] ** 2   

        with np.errstate(divide="ignore", invalid="ignore"):
            land_share = df["land_market_value"] / df["total_market_value"].replace(0, np.nan)
        df["land_share"] = land_share.clip(lower=0, upper=1).fillna(0)
        df["land_time"] = df["land_share"] * df["t"]


        # Imputation and Indicators
        df["missing_quality"] = df["quality_score"].isna().astype(int)
        df["missing_condition"] = df["condition_score"].isna().astype(int)
        df["quality_score"] = df["quality_score"].fillna(df["quality_score"].median())
        df["condition_score"] = df["condition_score"].fillna(df["condition_score"].median())
        df["is_view"] = df["is_view"].fillna(0).astype(int)

        # Interactions
        df["area_time"] = df["log_area"] * df["t"]
        df["area_quality"] = df["log_area"] * df["quality_score"]
        df["area_condition"] = df["log_area"] * df["condition_score"]   # NEW
        df["value_time"] = df["log_total_mv"] * df["t"]   

        df = df.replace([np.inf, -np.inf], np.nan)
        df["log_price"] = np.log(df["sale_price"])

        return df

    # -------------------------------------------------------------------
    # LOGIC 2: DYNAMIC TIERING (By Predicted Value)
    # -------------------------------------------------------------------
    def assign_dynamic_tiers_by_prediction(self, df: pd.DataFrame) -> tuple[pd.Series, dict | None]:
        """
        Pass 1: Fit a simple-but-rich base model to predict log_price,
        then use KMeans on predicted value to define LOW / MID / HIGH tiers.

        Returns:
            full_tier_series: pd.Series of "T1_LOW" / "T2_MID" / "T3_HIGH" / "ALL"
            tier_info: dict with predicted-price bands per tier (for reporting)
        """
        n = len(df)
        if n < MIN_ROWS_FOR_TIERING:
            # Not enough rows to safely split into tiers
            return pd.Series("ALL", index=df.index), None

        # A. Base model for tiering (richer than CORE_PREDICTORS)
        try:
            tier_cols = [c for c in TIERING_PREDICTORS if c in df.columns]
            if not tier_cols:
                self.stdout.write(self.style.WARNING("No tiering predictors available. Using ALL tier."))
                return pd.Series("ALL", index=df.index), None

            # Simple imputation: 0 for missing. For tiering we only need a ranking.
            X_full = df[tier_cols].fillna(0.0)
            X_full = sm.add_constant(X_full)

            y = df["log_price"]
            fit_mask = y.notna()
            if fit_mask.sum() < MIN_ROWS_FOR_TIERING:
                self.stdout.write(self.style.WARNING("Too few rows with log_price. Using ALL tier."))
                return pd.Series("ALL", index=df.index), None

            X_fit = X_full.loc[fit_mask]
            y_fit = y.loc[fit_mask]

            base_model = sm.OLS(y_fit, X_fit).fit()

            # Predict log_price for *all* rows (even previously NA ones)
            df["pred_log_price"] = base_model.predict(X_full)

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Base tiering model failed ({e}). Falling back to ALL tier.")
            )
            return pd.Series("ALL", index=df.index), None

        # B. KMeans clustering on predicted log_price
        valid_mask = df["pred_log_price"].notna()
        if valid_mask.sum() < 30:
            return pd.Series("ALL", index=df.index), None

        X_cluster = df.loc[valid_mask, "pred_log_price"].values.reshape(-1, 1)

        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X_cluster)

        # C. Map raw cluster labels to ordered tiers (LOW / MID / HIGH)
        pred_prices = np.exp(X_cluster[:, 0])  # back to price space for sorting
        cluster_df = pd.DataFrame({"label": labels, "pred_price": pred_prices})
        grouped = cluster_df.groupby("label")["pred_price"].mean().sort_values()
        sorted_clusters = grouped.index.tolist()  # from lowest to highest mean price

        mapping = {
            sorted_clusters[0]: "T1_LOW",
            sorted_clusters[1]: "T2_MID",
            sorted_clusters[2]: "T3_HIGH",
        }

        tier_series = pd.Series(index=df.index, dtype="object")
        tier_series.loc[valid_mask] = [mapping[l] for l in labels]

        # Fill any missing with "ALL"
        full_tier_series = pd.Series("ALL", index=df.index)
        full_tier_series.update(tier_series)

        # D. Predicted-price bands per tier (clean, non-overlapping)
        tier_info: dict[str, dict] = {}

        for lab in ["T1_LOW", "T2_MID", "T3_HIGH"]:
            mask = full_tier_series == lab
            if not mask.any():
                continue

            pred_vals = np.exp(df.loc[mask, "pred_log_price"].values)

            if len(pred_vals) < 5:
                lo = float(pred_vals.min())
                hi = float(pred_vals.max())
            else:
                lo = float(np.quantile(pred_vals, 0.05))
                hi = float(np.quantile(pred_vals, 0.95))

            tier_info[lab] = {
                "count": int(len(pred_vals)),
                "price_min": lo,
                "price_max": hi,
            }

        return full_tier_series, tier_info

    def apply_quantile_calibration(self, df: pd.DataFrame, label: str, n_bins: int = 10):
        """
        Value-band calibration:
        - splits by value proxy (V_proxy if available, else Vhat)
        - computes median ratio in each band
        - scales ratios so each band is centered at the overall median.

        Returns:
            df (with 'ratio_adj', 'calib_factor')
            calib_bands (list of dicts describing the bands)
        """
        # Choose value variable: V_proxy if present, else Vhat
        value_col = "V_proxy" if "V_proxy" in df.columns else "Vhat"

        # Fallback: if too small, don't bother
        if len(df) < 100 or df[value_col].nunique() < 5:
            df["calib_factor"] = 1.0
            df["ratio_adj"] = df["ratio"]
            return df, []

        max_bins = max(2, min(n_bins, df[value_col].nunique()))
        try:
            df["_val_bin"] = pd.qcut(
                df[value_col], max_bins, labels=False, duplicates="drop"
            )

            # Median ratio per band
            bin_meds = (
                df.groupby("_val_bin")["ratio"]
                .median()
                .rename("bin_median_ratio")
            )

            # Target center: overall median ratio
            target = df["ratio"].median()
            if np.isnan(target) or target <= 0:
                target = 1.0

            # Join band medians back on df
            df = df.join(bin_meds, on="_val_bin")

            # Calibration factor per row = target / band median
            df["calib_factor"] = target / df["bin_median_ratio"]
            df["ratio_adj"] = df["ratio"] * df["calib_factor"]

            # Package band info for storage / later use
            calib_bands = []
            for bin_id, bin_med in bin_meds.items():
                mask = df["_val_bin"] == bin_id
                vmin = float(df.loc[mask, value_col].min())
                vmax = float(df.loc[mask, value_col].max())
                factor = float(target / bin_med)
                calib_bands.append(
                    {
                        "bin": int(bin_id),
                        "value_min": vmin,
                        "value_max": vmax,
                        "median_ratio": float(bin_med),
                        "factor": factor,
                    }
                )

            return df, calib_bands

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Quantile calibration failed for {label}: {e}")
            )
            df["calib_factor"] = 1.0
            df["ratio_adj"] = df["ratio"]
            return df, []

    def compute_prb_drivers(self,df, predictors, ratio_col="ratio_adj"):
        """
        Quantifies how much each predictor contributes to PRB.
        Returns a ranked list of dicts:
        [
            {"predictor": "log_area", "slope": 0.12, "val_skew": 0.42, "score": 0.050},
            ...
        ]
        """

        results = []

        # Safety: can't compute if too few rows
        if len(df) < 60:
            return results

        # Value proxy for skew
        V_proxy = (df["sale_price"] + df["Vhat"]) / 2.0
        V_med = V_proxy.median()

        # Normalized ratio deviation
        med_ratio = df[ratio_col].median()
        y = (df[ratio_col] / med_ratio) - 1.0

        for p in predictors:
            if p not in df.columns:
                continue
            if df[p].nunique() < 3:
                continue  # no information content

            x = df[p]

            # Skip predictors with extreme missingness
            if x.isna().mean() > 0.20:
                continue

            # Standardize
            x_std = (x - x.mean()) / (x.std() + 1e-9)

            # Simple linear regression: y ~ x
            try:
                Xp = sm.add_constant(x_std)
                model = sm.OLS(y, Xp).fit()
                slope = float(model.params.get(p, np.nan))
            except:
                continue

            if np.isnan(slope):
                continue

            # Value skew = corr(predictor, value level)
            val_skew = float(np.corrcoef(x.fillna(0), V_proxy.fillna(0))[0, 1])

            # Composite score — magnitude of bias influence
            score = abs(slope) * (abs(val_skew) + 0.05)  # +0.05 ensures slope still matters

            results.append({
                "predictor": p,
                "slope": round(slope, 4),
                "val_skew": round(val_skew, 4),
                "score": round(score, 4),
            })

        # Sort highest → lowest PRB contribution
        results = sorted(results, key=lambda d: d["score"], reverse=True)

        return results

    def apply_prb_flattening(self, df: pd.DataFrame, label: str):
        """
        Second-stage calibration specifically to kill PRB:

        - Work on ln(ratio_adj) vs value deviation.
        - Fit: ln(ratio_adj) = a + b * val_dev
        - Then adjust: ln(ratio_final) = ln(ratio_adj) - b * val_dev
        => slope by value is ~0 in the trimmed range.

        Returns:
            df (with 'ratio_final' and 'prb_factor')
            prb_calib (dict with slope, n, etc.)
        """
        if "ratio_adj" not in df.columns or "V_proxy" not in df.columns:
            df["ratio_final"] = df.get("ratio_adj", df.get("ratio", 1.0))
            df["prb_factor"] = 1.0
            return df, None

        V_proxy = df["V_proxy"]
        ratio_adj = df["ratio_adj"]

        # Need positive ratios for log
        mask_pos = ratio_adj > 0
        if mask_pos.sum() < 60:
            df["ratio_final"] = ratio_adj
            df["prb_factor"] = 1.0
            return df, None

        # Trim central 10–90% on value for stable slope
        lo, hi = V_proxy.quantile([0.10, 0.90])
        mask_trim = mask_pos & V_proxy.between(lo, hi)

        if mask_trim.sum() < 60:
            df["ratio_final"] = ratio_adj
            df["prb_factor"] = 1.0
            return df, None

        # Value deviation (centered)
        med_val = V_proxy.median()
        val_dev = ((V_proxy / med_val) - 1.0).rename("val_dev")

        ln_ratio = np.log(ratio_adj)
        ln_ratio_trim = ln_ratio[mask_trim]
        val_dev_trim = val_dev[mask_trim]

        try:
            X = sm.add_constant(val_dev_trim)
            prb_model = sm.OLS(ln_ratio_trim, X).fit()
            b = float(prb_model.params.get("val_dev", np.nan))
        except Exception:
            df["ratio_final"] = ratio_adj
            df["prb_factor"] = 1.0
            return df, None

        if np.isnan(b):
            df["ratio_final"] = ratio_adj
            df["prb_factor"] = 1.0
            return df, None

        # Apply correction: ln(r_final) = ln(r_adj) - b * val_dev
        df["prb_factor"] = np.exp(-b * val_dev)
        df["ratio_final"] = ratio_adj * df["prb_factor"]

        prb_calib = {
            "slope_before": b,
            "n_used": int(mask_trim.sum()),
            "lo_val": float(lo),
            "hi_val": float(hi),
        }

        return df, prb_calib

    # -------------------------------------------------------------------
    # LOGIC 3: REGRESSION ENGINE (PASS 2 - Segmented)
    # -------------------------------------------------------------------
    def run_adjustment_model(self, df: pd.DataFrame, label: str, tier_name: str):
        # --- Clean & Trim ---
        if len(df) < 30:
            return None

        trim = TIER_TRIMS.get(tier_name, TIER_TRIMS["ALL"])
        p_lo, p_hi = df["sale_price"].quantile(trim["price"])
        a_lo, a_hi = df["living_area"].quantile(trim["area"])

        df = df[
            df["sale_price"].between(p_lo, p_hi) &
            df["living_area"].between(a_lo, a_hi)
        ].copy()

        if len(df) < 30:
            return None

        # ----------------------------------------------------------------------
        # 1. TIER DUMMIES
        # ----------------------------------------------------------------------
        df["is_T1"] = 1 if tier_name == "T1_LOW" else 0
        df["is_T2"] = 1 if tier_name == "T2_MID" else 0
        df["is_T3"] = 1 if tier_name == "T3_HIGH" else 0

        # ----------------------------------------------------------------------
        # 2. TIER-SPECIFIC TIME TRENDS
        # ----------------------------------------------------------------------
        df["t_T1"] = df["t"] * df["is_T1"]
        df["t_T2"] = df["t"] * df["is_T2"]
        df["t_T3"] = df["t"] * df["is_T3"]

        df["t_sq_T1"] = df["t_sq"] * df["is_T1"]
        df["t_sq_T2"] = df["t_sq"] * df["is_T2"]
        df["t_sq_T3"] = df["t_sq"] * df["is_T3"]

        # ----------------------------------------------------------------------
        # 3. TIER-SPECIFIC VALUE CURVATURE (fixes PRB)
        # ----------------------------------------------------------------------
        df["mv_T1"]     = df["log_total_mv"]    * df["is_T1"]
        df["mv_sq_T1"]  = df["log_total_mv_sq"] * df["is_T1"]

        df["mv_T2"]     = df["log_total_mv"]    * df["is_T2"]
        df["mv_sq_T2"]  = df["log_total_mv_sq"] * df["is_T2"]

        df["mv_T3"]     = df["log_total_mv"]    * df["is_T3"]
        df["mv_sq_T3"]  = df["log_total_mv_sq"] * df["is_T3"]

        # ----------------------------------------------------------------------
        # 4. TIME × VALUE INTERACTION (PRB KILLER)
        # ----------------------------------------------------------------------
        df["t_mv"]    = df["t"]    * df["log_total_mv"]
        df["t_sq_mv"] = df["t_sq"] * df["log_total_mv"]

        df["t_mv_T1"]    = df["t_mv"]    * df["is_T1"]
        df["t_sq_mv_T1"] = df["t_sq_mv"] * df["is_T1"]

        df["t_mv_T2"]    = df["t_mv"]    * df["is_T2"]
        df["t_sq_mv_T2"] = df["t_sq_mv"] * df["is_T2"]

        df["t_mv_T3"]    = df["t_mv"]    * df["is_T3"]
        df["t_sq_mv_T3"] = df["t_sq_mv"] * df["is_T3"]

        # ----------------------------------------------------------------------
        # 5. TIER-SPECIFIC AREA CURVATURE (low-tier bias)
        # ----------------------------------------------------------------------
        df["area_T1"]    = df["log_area"]    * df["is_T1"]
        df["area_sq_T1"] = df["log_area_sq"] * df["is_T1"]

        df["area_T2"]    = df["log_area"]    * df["is_T2"]
        df["area_sq_T2"] = df["log_area_sq"] * df["is_T2"]

        df["area_T3"]    = df["log_area"]    * df["is_T3"]
        df["area_sq_T3"] = df["log_area_sq"] * df["is_T3"]

        # ----------------------------------------------------------------------
        # 6. Build mandatory predictors (per-tier)
        # ----------------------------------------------------------------------
        if tier_name == "T1_LOW":
            mandatory = CORE_PREDICTORS + [
                "t_T1", "t_sq_T1",
                "mv_T1", "mv_sq_T1",
                "t_mv_T1", "t_sq_mv_T1",
                "area_T1", "area_sq_T1",
            ]

        elif tier_name == "T2_MID":
            mandatory = CORE_PREDICTORS + [
                "t_T2", "t_sq_T2",
                "mv_T2", "mv_sq_T2",
                "t_mv_T2", "t_sq_mv_T2",
                "area_T2", "area_sq_T2",
            ]

        elif tier_name == "T3_HIGH":
            mandatory = CORE_PREDICTORS + [
                "t_T3", "t_sq_T3",
                "mv_T3", "mv_sq_T3",
                "t_mv_T3", "t_sq_mv_T3",
                "area_T3", "area_sq_T3",
            ]
        else:
            mandatory = CORE_PREDICTORS

        # ----------------------------------------------------------------------
        # 7. Stepwise variable selection
        # ----------------------------------------------------------------------
        final_predictors = self.select_predictors_stepwise(
            df,
            y_col="log_price",
            mandatory=mandatory,
            candidates=CANDIDATE_PREDICTORS,
        )

        # ----------------------------------------------------------------------
        # 8. Fit model
        # ----------------------------------------------------------------------
        df = df.dropna(subset=final_predictors + ["log_price"])
        final_predictors = [c for c in final_predictors if df[c].nunique() > 1]
        if len(df) < len(final_predictors) + 5:
            return None

        X = sm.add_constant(df[final_predictors])
        y = df["log_price"]

        try:
            model = sm.OLS(y, X).fit(cov_type="HC3")
        except Exception:
            return None

        # ----------------------------------------------------------------------
        # 9. Predictions + Smearing
        # ----------------------------------------------------------------------
        df["pred_ln"] = model.predict(X)
        smear = np.exp(model.resid).mean()
        df["Vhat"] = np.exp(df["pred_ln"]) * smear
        
        # INTERNAL RATIO: Sale / Appraised (S/A)
        # Kept as S/A because your helper functions (quantile_calibration) likely expect this direction.
        df["ratio"] = df["sale_price"] / df["Vhat"]
        
        df["V_proxy"] = (df["sale_price"] + df["Vhat"]) / 2.0

        # ----------------------------------------------------------------------
        # 10. Value-band calibration (quantile)
        # ----------------------------------------------------------------------
        df, calib_bands = self.apply_quantile_calibration(df, label)

        # ----------------------------------------------------------------------
        # 10b. PRB-flattening calibration (kills residual slope by value)
        # ----------------------------------------------------------------------
        df, prb_calib = self.apply_prb_flattening(df, label)
        
        # INTERNAL S/A RATIO (Adjusted)
        # Used for any internal logic that expects Sale / Value
        ratio_internal_sa = df.get("ratio_final", df.get("ratio_adj", df["ratio"]))

        # ----------------------------------------------------------------------
        # 11. IAAO STATISTICS (COD, PRD, PRB) - CORRECTED
        # ----------------------------------------------------------------------
        # A. CONVERT TO IAAO RATIO (Appraised / Sale)
        # Since ratio_internal_sa is (Sale / Appraised), we invert it.
        # This ensures all stats below are based on the industry standard A/S ratio.
        df["iaao_ratio"] = 1.0 / ratio_internal_sa
        
        iaao_ratio = df["iaao_ratio"]
        med_ratio = iaao_ratio.median()

        # B. COD (Standard 3.1.2: Average deviation from median)
        # (Mean Absolute Deviation / Median) * 100
        abs_dev = np.abs(iaao_ratio - med_ratio)
        cod = (abs_dev.mean() / med_ratio) * 100

        # C. PRD (Standard 3.1.3: Mean Ratio / Weighted Mean Ratio)
        mean_ratio = iaao_ratio.mean()
        # Weighted mean is Sum(Appraised) / Sum(Sale)
        # Note: If ratio_internal_sa included adjustments (calib_factor), we must estimate 
        # the 'final' Vhat for the weighted mean.
        # Vhat_final = Sale_Price * iaao_ratio
        vhat_final = df["sale_price"] * iaao_ratio
        weighted_mean = vhat_final.sum() / df["sale_price"].sum()
        prd = mean_ratio / weighted_mean

        # D. PRB Drivers (passed the CORRECTED ratio)
        # This will now correctly identify drivers of A/S ratio bias
        prb_drivers = self.compute_prb_drivers(df, final_predictors, ratio_col="iaao_ratio")

        # E. PRB (Standard 3.1.4: Regression on Log Base 2 of Value)
        # We need to trim extremes to get a stable PRB (IAAO suggests trimming ratios <0.5 or >2.0 for this test)
        # We also reuse your value proxy logic.
        V_proxy = df["V_proxy"]
        
        # Trim specifically for PRB calculation
        # 1. Trim top/bottom 5% of Value
        val_lo, val_hi = V_proxy.quantile([0.05, 0.95])
        # 2. Trim extreme ratios (IAAO suggestion to avoid outlier leverage)
        mask_prb = (
            V_proxy.between(val_lo, val_hi) & 
            iaao_ratio.between(0.5, 2.0)
        )
        
        if mask_prb.sum() > 30:
            # X: Log Base 2 of (Value / Median Value)
            # This makes the coefficient represent "change in ratio for every doubling of value"
            x_prb = np.log2(V_proxy[mask_prb] / V_proxy[mask_prb].median())
            
            # Y: (Ratio - Median) / Median
            # Percentage difference from the median ratio
            y_prb = (iaao_ratio[mask_prb] - med_ratio) / med_ratio
            
            try:
                # OLS Regression
                prb_model = sm.OLS(y_prb, sm.add_constant(x_prb)).fit()
                prb = float(prb_model.params.iloc[1]) # The slope coefficient
            except Exception:
                prb = np.nan
        else:
            prb = np.nan

        # ----------------------------------------------------------------------
        # 12. Package summary
        # ----------------------------------------------------------------------
        summary = {
            "label": label,
            "market_group": label.split("__")[0],
            "value_tier": tier_name,
            "n": int(len(df)),
            "r2": float(model.rsquared),
            "adj_r2": float(model.rsquared_adj),
            "COD": float(round(cod, 2)),
            "PRD": float(round(prd, 3)),
            "median_ratio": float(round(med_ratio, 3)),
            "PRB": float(round(prb, 3)) if not np.isnan(prb) else None,
            "PRB_drivers": prb_drivers,
            "PRB_calibration": prb_calib,
            "variables": final_predictors,
            "calib_bands": calib_bands,
        }

        return summary, model

    # -------------------------------------------------------------------
    # MAIN EXECUTION
    # -------------------------------------------------------------------
    def handle(self, *args, **options):
        run_id = options["run_id"] or datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        if options["undo"]:
            self.handle_undo(options.get("run_id"))
            return

        self.stdout.write(self.style.SUCCESS(f"Starting Two-Pass Run: {run_id}"))

        # Load Data & Initial Clean
        df = pd.read_sql_query("SELECT * FROM sale_regression_sfr", connection)
        df = df.dropna(subset=["sale_price", "living_area", "age"]).copy()
        df = df[df["sale_price"] > 10000]
        df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
        df = df[df["sale_date"].notna()]

        # Feature Engineering (Done once for all passes)
        df = self.engineer_features(df)

        mg_col = options["market_group_col"]

        run_stats_list = []
        coef_rows = []

        # Decide grouping mode
        if options["countywide"]:
            group_items = [("COUNTYWIDE", df)]
        else:
            group_items = df.groupby(mg_col)

        # Iterate Market Groups (or just the one big group)
        for group, subdf in group_items:
            subdf = subdf.copy()
            self.stdout.write(self.style.SUCCESS(f"\n=== GROUP: {group} ==="))

            # If small market, skip tiering and run single ALL model
            if len(subdf) < 1300:
                self.stdout.write(f"   [INFO] {group}: small N ({len(subdf)}). Using ALL tier (no value segmentation).")
                subdf["value_tier"] = "ALL"
                tiers = subdf["value_tier"]
                tier_info = {"ALL": {
                    "count": int(len(subdf)),
                    "price_min": float(subdf["sale_price"].quantile(0.05)),
                    "price_max": float(subdf["sale_price"].quantile(0.95)),
                }}
            else:
                # Normal path: dynamic tiering
                tiers, tier_info = self.assign_dynamic_tiers_by_prediction(subdf)
                subdf["value_tier"] = tiers

            # B. Pass 2: Segmented Regression
            for tier_label, tier_df in subdf.groupby("value_tier"):
                label_str = f"{group}__{tier_label}"
                t_stats = tier_info.get(tier_label, {}) if tier_info else {}

                res = self.run_adjustment_model(tier_df, label_str, tier_label)
                if not res:
                    self.stdout.write(f"   [{tier_label}] Skipped (Insufficient data after trim/engineer).")
                    continue

                stats, model = res

                stats["price_min"] = t_stats.get("price_min", df["sale_price"].min())
                stats["price_max"] = t_stats.get("price_max", df["sale_price"].max())

                vars_list = [v for v in stats["variables"] if v not in CORE_PREDICTORS]
                prb_val = stats.get("PRB")
                self.stdout.write(
                    f"   [{tier_label}] ${stats['price_min']:,.0f}-${stats['price_max']:,.0f} "
                    f"| COD={stats['COD']:.2f} PRD={stats['PRD']:.3f}"
                    + (f" PRB={prb_val:.3f}" if prb_val is not None else "")
                    + f" | Added Vars: {', '.join(vars_list) if vars_list else '(None)'}"
                )

                run_stats_list.append(stats)

                for term, beta in model.params.items():
                    coef_rows.append(
                        AdjustmentCoefficient(
                            market_group=label_str,
                            term=term,
                            beta=float(beta),
                            beta_se=float(model.bse.get(term, 0)),
                            run_id=run_id,
                        )
                    )

        # Final Save
        if not options["dry_run"] and run_stats_list:
            self.stdout.write("\nSaving to Database...")
            with transaction.atomic():
                AdjustmentRunSummary.objects.update_or_create(
                    run_id=run_id,
                    defaults={"stats": run_stats_list},
                )
                AdjustmentCoefficient.objects.bulk_create(coef_rows, batch_size=1000)
            self.stdout.write(self.style.SUCCESS("✅ Two-Pass Run Complete. Check UI for new statistics."))
        else:
            self.stdout.write("Dry run or no results found.")

    