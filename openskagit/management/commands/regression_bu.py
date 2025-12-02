import datetime
import json
import os
from typing import Any, List

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.stats.outliers_influence as sm_influence # Ensure this is present
from sklearn.cluster import KMeans
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.conf import settings
from openai import OpenAI
from dotenv import load_dotenv

# App imports - adjust if your app name is different
from openskagit.models import AdjustmentCoefficient, AdjustmentRunSummary
from openskagit.ai.methodology_schemas import ModelMethodologyPage

load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------
MIN_ROWS_FOR_TIERING = 350
REFERENCE_AGE_YEAR = 2025

TIER_TRIMS = {
    "T1_LOW":   {"price": (0.05, 0.95), "area": (0.05, 0.95)},
    "T2_MID":   {"price": (0.05, 0.95), "area": (0.02, 0.98)},
    "T3_HIGH":  {"price": (0.05, 0.99), "area": (0.02, 0.98)},
    "ALL":      {"price": (0.05, 0.95), "area": (0.02, 0.98)},
}

# --- GROUP 1: BASE VARIABLES (Tier-Specific Interactions) ---
# Any variable listed here will automatically get _T1, _T2, _T3 suffixes
# and be interacted with the tier dummy when running that specific tier.
TIER_INTERACTION_VARS = [
    "t", 
    "t_sq", 
    #"log_total_mv", 
    # "log_total_mv_sq", # Uncomment if you want curvature per tier
    #"t_mv", 
    #"t_sq_mv",
    "log_area", 
    "log_area_sq",
    "log_lot",
    "quality_score",
]

# --- GROUP 2: CORE VARIABLES (Always Included) ---
CORE_PREDICTORS = [
    "log_area",
    "log_age",
    #"land_time",
    "t",
    "t_sq",
    #"log_total_mv",
    #"log_total_mv_sq",
    #"area_time",        
    "quality_score",
    "condition_score",
]

# --- GROUP 3: CANDIDATE VARIABLES (Stepwise Selection) ---
CANDIDATE_PREDICTORS = [
    "log_lot",
    "land_share",
    #"log_land_value",
    "has_garage",
    "has_basement",
    "is_view",
    "missing_quality",
    "missing_condition",
    #"area_condition",   
    #"value_time",       
    "log_elev",
    #"area_elev",
    #"slope_pct",
    #"slope_area",
    "log_major_road",
    # New additions
    "log_far",
    "log_eff_age",
    "baths_per_bed",
    "log_lot_sq",
]

# --- GROUP 4: TIERING PREDICTORS (Used for Clustering only) ---
TIERING_PREDICTORS = CORE_PREDICTORS + [
    "log_lot",
    "has_garage",
    "has_basement",
    "is_view",
    "land_share",
    #"log_land_value",
]

# --- REPORTING GROUPS ---
DRIVER_GROUPS = {
    "Size & layout": {"log_area", "log_area_sq"},
    "Age & depreciation": {"log_age"},
    "Quality & condition": {"quality_score", "condition_score", "area_quality", "area_condition"},
    "Lot & land": {"log_lot", "log_land_value", "land_share"},
    "Time & market cycle": {"t", "t_sq", "area_time", "land_time", "value_time"},
    "Location & extras": {"is_view", "has_garage", "has_basement"},
}

class Command(BaseCommand):
    help = "Two-Pass Regression: Tiering by Predicted Value, then Stepwise Selection."

    def add_arguments(self, parser):
        parser.add_argument("--market-group-col", type=str, default="valuation_area")
        parser.add_argument("--run-id", type=str, default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--undo", action="store_true")
        parser.add_argument("--countywide", action="store_true")

    # -------------------------------------------------------------------
    # UTILITY METHODS
    # -------------------------------------------------------------------
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

    def select_predictors_stepwise(self, df: pd.DataFrame, y_col: str, mandatory: list, candidates: list):
        """Forward Stepwise Selection using AIC."""
        selected = list(mandatory)
        # Only consider candidates that actually exist and have variation
        pool = [c for c in candidates if c not in selected and c in df.columns and df[c].nunique() > 1]
        
        X_base = sm.add_constant(df[selected])
        y = df[y_col]

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

    def ensure_age_column(self, df: pd.DataFrame) -> pd.DataFrame:
        if "age" not in df.columns:
            if "age_raw" in df.columns:
                df["age"] = df["age_raw"]
            elif "year_built" in df.columns:
                df["age"] = np.where(df["year_built"].notna(), REFERENCE_AGE_YEAR - df["year_built"], np.nan)
            else:
                df["age"] = np.nan
        df["age"] = df["age"].clip(lower=0)
        return df

    # -------------------------------------------------------------------
    # FEATURE ENGINEERING
    # -------------------------------------------------------------------
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies feature transformations. All potential features are calculated here."""
        
        # 1. Base Log Transforms
        df["log_area"] = np.log(df["living_area"].clip(lower=1))
        log_area_mean = df["log_area"].mean()
        df["log_lot"] = np.log1p(df["lot_acres"].clip(lower=0))
        df["log_age"] = np.log1p(df["age"].clip(lower=0))
        df["log_area_sq"] = (df["log_area"] - log_area_mean) ** 2
        
        ###TESTS
        df["log_far"] = np.log1p(df["floor_area_ratio"].clip(lower=0)) # Or just df["floor_area_ratio"]
        df["eff_age"] = np.where(df["eff_year_built"].notna(), REFERENCE_AGE_YEAR - df["eff_year_built"], df["age"])
        df["log_eff_age"] = np.log1p(df["eff_age"].clip(lower=0))
        df["baths_per_bed"] = (df["bathrooms"] + 0.5) / (df["bedrooms"].clip(lower=1))
        df["age_quality"] = df["log_age"] * df["quality_score"]
        df["area_lot"] = df["log_area"] * df["log_lot"]

        # 2. Time
        ANCHOR = pd.Timestamp("2015-01-01")
        df["t"] = (df["sale_date"] - ANCHOR).dt.days / 30.4375
        t_mean = df["t"].mean()
        df["t_sq"] = (df["t"] - t_mean) ** 2

        # 3. Value & Ratios
        df["log_land_value"] = np.log1p(df["land_market_value"].clip(lower=0))
        df["log_total_mv"] = np.log1p(df["total_market_value"].clip(lower=0))
        df["log_total_mv_sq"] = df["log_total_mv"] ** 2

        with np.errstate(divide="ignore", invalid="ignore"):
            land_share = df["land_market_value"] / df["total_market_value"].replace(0, np.nan)
        df["land_share"] = land_share.clip(lower=0, upper=1).fillna(0)
        
        # 4. Imputations
        df["missing_quality"] = df["quality_score"].isna().astype(int)
        df["missing_condition"] = df["condition_score"].isna().astype(int)
        df["quality_score"] = df["quality_score"].fillna(df["quality_score"].median())
        df["condition_score"] = df["condition_score"].fillna(df["condition_score"].median())
        df["is_view"] = df["is_view"].fillna(0).astype(int)

        # 5. Geodata / Extra
        df["elev"] = df["elev"].fillna(0)
        df["log_elev"] = np.log1p(df["elev"])
        df["slope_pct"] = df["slope"].fillna(0)
        df["dist_major_road"] = df["dist_major_road"].fillna(0)
        df["log_major_road"] = np.log1p(df["dist_major_road"])

        # 6. INTERACTIONS (Calculate ALL here; select via config later)
        df["land_time"] = df["land_share"] * df["t"]
        df["area_time"] = df["log_area"] * df["t"]
        df["value_time"] = df["log_total_mv"] * df["t"]
        
        df["area_quality"] = df["log_area"] * df["quality_score"]
        df["area_condition"] = df["log_area"] * df["condition_score"]
        
        df["area_elev"] = df["log_area"] * df["log_elev"]
        df["slope_area"] = df["slope_pct"] * df["log_area"]

        # PRB Specific
        df["t_mv"] = df["t"] * df["log_total_mv"]
        df["t_sq_mv"] = df["t_sq"] * df["log_total_mv"]

        # Final Prep
        df = df.replace([np.inf, -np.inf], np.nan)
        df["log_price"] = np.log(df["sale_price"])

        return df

    # -------------------------------------------------------------------
    # DYNAMIC TIERING
    # -------------------------------------------------------------------
    def assign_dynamic_tiers_by_prediction(self, df: pd.DataFrame) -> tuple[pd.Series, dict | None]:
        n = len(df)
        if n < MIN_ROWS_FOR_TIERING:
            return pd.Series("ALL", index=df.index), None

        try:
            tier_cols = [c for c in TIERING_PREDICTORS if c in df.columns]
            X_full = sm.add_constant(df[tier_cols].fillna(0.0))
            y = df["log_price"]
            
            fit_mask = y.notna()
            if fit_mask.sum() < MIN_ROWS_FOR_TIERING:
                return pd.Series("ALL", index=df.index), None

            base_model = sm.OLS(y[fit_mask], X_full.loc[fit_mask]).fit()
            df["pred_log_price"] = base_model.predict(X_full)

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Tiering failed ({e}). Using ALL."))
            return pd.Series("ALL", index=df.index), None

        # KMeans
        valid_mask = df["pred_log_price"].notna()
        if valid_mask.sum() < 30:
            return pd.Series("ALL", index=df.index), None

        X_cluster = df.loc[valid_mask, "pred_log_price"].values.reshape(-1, 1)
        labels = KMeans(n_clusters=3, random_state=42, n_init=10).fit_predict(X_cluster)

        # Order Tiers
        cluster_df = pd.DataFrame({"label": labels, "pred_price": np.exp(X_cluster[:, 0])})
        sorted_clusters = cluster_df.groupby("label")["pred_price"].mean().sort_values().index.tolist()
        
        mapping = {
            sorted_clusters[0]: "T1_LOW",
            sorted_clusters[1]: "T2_MID",
            sorted_clusters[2]: "T3_HIGH",
        }
        
        tier_series = pd.Series("ALL", index=df.index)
        tier_series.loc[valid_mask] = [mapping[l] for l in labels]

        # Stats
        tier_info = {}
        for lab in ["T1_LOW", "T2_MID", "T3_HIGH"]:
            mask = tier_series == lab
            if mask.any():
                pred_vals = np.exp(df.loc[mask, "pred_log_price"].values)
                tier_info[lab] = {
                    "count": int(len(pred_vals)),
                    "price_min": float(np.quantile(pred_vals, 0.05)),
                    "price_max": float(np.quantile(pred_vals, 0.95)),
                }

        return tier_series, tier_info

    # -------------------------------------------------------------------
    # REGRESSION ENGINE (Consolidated)
    # -------------------------------------------------------------------
    def run_adjustment_model(self, df: pd.DataFrame, label: str, tier_name: str):
        # 1. Clean & Trim
        if len(df) < 30: return None
        
        trim = TIER_TRIMS.get(tier_name, TIER_TRIMS["ALL"])
        df = df[
            df["sale_price"].between(df["sale_price"].quantile(trim["price"][0]), df["sale_price"].quantile(trim["price"][1])) &
            df["living_area"].between(df["living_area"].quantile(trim["area"][0]), df["living_area"].quantile(trim["area"][1]))
        ].copy()

        if len(df) < 30: return None

        # 2. Dynamic Interactions
        # This replaces the manual if/else blocks for T1/T2/T3
        tier_suffix = None
        if tier_name == "T1_LOW": tier_suffix = "T1"
        elif tier_name == "T2_MID": tier_suffix = "T2"
        elif tier_name == "T3_HIGH": tier_suffix = "T3"

        mandatory = list(CORE_PREDICTORS)
        
        # ... inside run_adjustment_model
        if tier_suffix:
            dummy_col = f"value_tier_{tier_suffix}"
            df[dummy_col] = 1.0
            # Generate interactions
            for var in TIER_INTERACTION_VARS:
                if var in df.columns:
                    inter_col = f"{var}_{tier_suffix}"
                    df[inter_col] = df[var] * df[dummy_col]
                    mandatory.append(inter_col)
                    # <<< CRITICAL FIX HERE: Remove the base variable from the mandatory list
                    #     if its interaction is added.
                    if var in mandatory:
                        mandatory.remove(var)
            df.drop(columns=[dummy_col], inplace=True)

        # 3. Safety Filter: Ensure variables exist
        mandatory = [c for c in mandatory if c in df.columns]
        candidates = [c for c in CANDIDATE_PREDICTORS if c in df.columns and c not in mandatory]

        # 4. Stepwise Selection & Fit
        final_predictors = self.select_predictors_stepwise(df, "log_price", mandatory, candidates)
        
        df = df.dropna(subset=final_predictors + ["log_price"])
        final_predictors = [c for c in final_predictors if df[c].nunique() > 1] # Remove constants

        if len(df) < len(final_predictors) + 5: return None

        X = sm.add_constant(df[final_predictors])
        try:
            model = sm.OLS(df["log_price"], X).fit(cov_type="HC3")
        except Exception:
            return None

        # 5. Post-Processing (Values, Ratios, Calibration)
        df["pred_ln"] = model.predict(X)
        df["residual"] = model.resid # Add residual column for chart data
        smear = np.exp(model.resid).mean()
        df["Vhat"] = np.exp(df["pred_ln"]) * smear
        df["ratio"] = df["sale_price"] / df["Vhat"]
        df["V_proxy"] = (df["sale_price"] + df["Vhat"]) / 2.0

        df, calib_bands = self.apply_quantile_calibration(df, label)
        df, prb_calib = self.apply_prb_flattening(df, label)
        
        # 6. Diagnostics
        ratio_use = df.get("ratio_final", df.get("ratio_adj", df["ratio"]))
        
        # Basic stats
        med = ratio_use.median()
        cod = (np.abs(ratio_use - med) / med).median() * 100
        
        # PRB
        prb_drivers = self.compute_prb_drivers(df.assign(ratio_iaao=ratio_use), final_predictors, ratio_col="ratio_iaao")
        value_driver_groups, value_drivers = summarize_value_drivers_from_prb(prb_drivers)

        # PRD
        df_sorted = df.sort_values("V_proxy")
        mid = len(df_sorted) // 2
        prd = df_sorted.iloc[mid:][ratio_use.name].mean() / df_sorted.iloc[:mid][ratio_use.name].mean()
        
        # PRB Slope
        try:
            vp = df["V_proxy"]
            mask = vp.between(vp.quantile(0.10), vp.quantile(0.90))
            # Fix for FutureWarning: params[1] is position-based access
            prb_model = sm.OLS((ratio_use[mask]/med)-1, sm.add_constant(((vp[mask]/vp.median())-1))).fit()
            prb = float(prb_model.params[1])
        except:
            prb = np.nan

        # 7. Summary Package
        # --- FIX FOR JSON SERIALIZATION ERROR ---
        
        # 1. Sample the data
        chart_df = df.sample(min(len(df), 5000), random_state=42).reset_index(drop=True)
        
        # 2. Define the columns and ensure residual is present
        chart_cols = ["ratio", "ratio_final", "Vhat", "sale_price", "log_area", "t"]
        if "residual" in chart_df.columns:
            chart_cols.append("residual")
            
        # 3. Create a clean DataFrame with standard Python float types
        clean_chart_data = pd.DataFrame()
        for col in chart_cols:
             if col in chart_df.columns:
                clean_chart_data[col] = chart_df[col].astype(float)
        # --- END FIX ---
        
        summary = {
            "label": label,
            "market_group": label.split("__")[0],
            "value_tier": tier_name,
            "n": int(len(df)),
            "r2": float(model.rsquared),
            "adj_r2": float(model.rsquared_adj),
            "COD": float(round(cod, 2)),
            "PRD": float(round(prd, 3)),
            "median_ratio": float(round(med, 3)),
            "PRB": float(round(prb, 3)) if not np.isnan(prb) else None,
            "variables": final_predictors,
            "PRB_drivers": prb_drivers,
            "PRB_calibration": prb_calib,
            "calib_bands": calib_bands,
            "value_driver_groups": value_driver_groups,
            "value_drivers": value_drivers,
            "chart_data": clean_chart_data.to_dict(orient="records") # Use the clean data
        }

        diagnostics = diagnostics_for_segment(df, model, final_predictors, summary, mandatory=mandatory)

        return summary, model, diagnostics

    # -------------------------------------------------------------------
    # CALIBRATION HELPERS (Keep as is)
    # -------------------------------------------------------------------
    def apply_quantile_calibration(self, df: pd.DataFrame, label: str, n_bins: int = 10):
        value_col = "V_proxy" if "V_proxy" in df.columns else "Vhat"
        if len(df) < 100 or df[value_col].nunique() < 5:
            df["calib_factor"] = 1.0; df["ratio_adj"] = df["ratio"]
            return df, []
        
        try:
            df["_val_bin"] = pd.qcut(df[value_col], max(2, min(n_bins, df[value_col].nunique())), labels=False, duplicates="drop")
            bin_meds = df.groupby("_val_bin")["ratio"].median()
            target = df["ratio"].median()
            
            df = df.join(bin_meds.rename("bin_med"), on="_val_bin")
            df["calib_factor"] = target / df["bin_med"]
            df["ratio_adj"] = df["ratio"] * df["calib_factor"]

            calib_bands = []
            for b_id, b_med in bin_meds.items():
                mask = df["_val_bin"] == b_id
                calib_bands.append({
                    "bin": int(b_id), # Ensure bin ID is standard int
                    "value_min": float(df.loc[mask, value_col].min()), # Ensure standard float
                    "value_max": float(df.loc[mask, value_col].max()), # Ensure standard float
                    "factor": float(target / b_med) # Ensure standard float
                })
            return df, calib_bands
        except Exception:
            df["calib_factor"] = 1.0; df["ratio_adj"] = df["ratio"]
            return df, []

    def apply_prb_flattening(self, df: pd.DataFrame, label: str):
        if "ratio_adj" not in df.columns: return df, None
        
        try:
            vp = df["V_proxy"]
            mask = (df["ratio_adj"] > 0) & vp.between(vp.quantile(0.10), vp.quantile(0.90))
            if mask.sum() < 60: raise ValueError
            
            val_dev = ((vp[mask] / vp.median()) - 1.0)
            ln_ratio = np.log(df.loc[mask, "ratio_adj"])
            b = sm.OLS(ln_ratio, sm.add_constant(val_dev)).fit().params[1]
            
            df["prb_factor"] = np.exp(-b * ((vp/vp.median())-1.0))
            df["ratio_final"] = df["ratio_adj"] * df["prb_factor"]
            return df, {"slope_before": float(b), "n_used": int(mask.sum())}
        except:
            df["ratio_final"] = df.get("ratio_adj", df["ratio"])
            return df, None

    def compute_prb_drivers(self, df, predictors, ratio_col="ratio_adj"):
        if len(df) < 60: return []
        results = []
        y = (df[ratio_col] / df[ratio_col].median()) - 1.0
        vp = (df["sale_price"] + df["Vhat"]) / 2.0
        
        for p in predictors:
            if p not in df.columns or df[p].nunique() < 3: continue
            try:
                x_std = (df[p] - df[p].mean()) / (df[p].std() + 1e-9)
                slope = sm.OLS(y, sm.add_constant(x_std)).fit().params.get(p, np.nan)
                if np.isnan(slope): continue
                val_skew = np.corrcoef(df[p].fillna(0), vp.fillna(0))[0, 1]
                results.append({
                    "predictor": p, "slope": round(float(slope), 4),
                    "val_skew": round(float(val_skew), 4),
                    "score": round(abs(slope) * (abs(val_skew) + 0.05), 4)
                })
            except: continue
        return sorted(results, key=lambda d: d["score"], reverse=True)

    # -------------------------------------------------------------------
    # MAIN EXECUTION
    # -------------------------------------------------------------------
    def handle(self, *args, **options):
        run_id = options["run_id"] or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        if options["undo"]: self.handle_undo(options.get("run_id")); return

        self.stdout.write(self.style.SUCCESS(f"Starting Run: {run_id}"))
        
        # Load & Prep
        df = pd.read_sql_query("SELECT * FROM sale_regression_sfr", connection)
        df = self.ensure_age_column(df).dropna(subset=["sale_price", "living_area", "age"])
        df = df[(df["sale_price"] > 10000) & (df["sale_date"].notna())].copy()
        df["sale_date"] = pd.to_datetime(df["sale_date"])
        df = self.engineer_features(df)

        mg_col = options["market_group_col"]
        run_stats = []
        coef_rows = []
        run_diag = {
            "run_id": run_id,
            "generated_at": datetime.datetime.utcnow().isoformat(),
            "market_group_col": mg_col,
            "segments": []
        }

        # Grouping
        groups = [("COUNTYWIDE", df)] if options["countywide"] else df.groupby(mg_col)

        for group, subdf in groups:
            subdf = subdf.copy()
            self.stdout.write(f"\n=== {group} ===")

            # Tiering
            if len(subdf) < 1300:
                tiers = pd.Series("ALL", index=subdf.index)
                tier_info = {}
            else:
                tiers, tier_info = self.assign_dynamic_tiers_by_prediction(subdf)
            subdf["value_tier"] = tiers

            # Segment Processing
            for tier_label, tier_df in subdf.groupby("value_tier"):
                label_str = f"{group}__{tier_label}"
                res = self.run_adjustment_model(tier_df, label_str, tier_label)
                if not res: continue
                
                stats, model, diag = res
                
                # Reporting
                t_stats = tier_info.get(tier_label, {})
                stats["price_min"] = float(t_stats.get("price_min", subdf["sale_price"].min()))
                stats["price_max"] = float(t_stats.get("price_max", subdf["sale_price"].max()))
                
                run_stats.append(stats)
                diag["tier_price_band"] = {"tier": tier_label, "min": stats["price_min"], "max": stats["price_max"]}
                run_diag["segments"].append(diag)
                
                added = [v for v in stats["variables"] if v not in CORE_PREDICTORS]
                self.stdout.write(f"   [{tier_label}] COD={stats['COD']:.1f} PRD={stats['PRD']:.3f} | +Vars: {len(added)}")

                for term, beta in model.params.items():
                    coef_rows.append(AdjustmentCoefficient(
                        market_group=label_str, term=term, beta=float(beta),
                        beta_se=float(model.bse.get(term, 0)), run_id=run_id
                    ))

        # Save
        if not options["dry_run"] and run_stats:
            with transaction.atomic():
                AdjustmentRunSummary.objects.create(run_id=run_id, stats=run_stats)
                AdjustmentCoefficient.objects.bulk_create(coef_rows)
            
            run_diag["segment_count"] = len(run_diag["segments"])
            run_diag["totals"] = {
                "observations": int(sum(seg["performance"]["n"] for seg in run_diag["segments"])),
                "tiers": sorted({seg["value_tier"] for seg in run_diag["segments"]}),
            }
            
            with open(os.path.join(settings.BASE_DIR, f"diagnostics_{run_id}.json"), "w") as f:
                json.dump(run_diag, f, indent=2)
                
            self.stdout.write(self.style.SUCCESS("✅ Run Complete."))

# -------------------------------------------------------------------
# REPORTING HELPERS
# -------------------------------------------------------------------
def summarize_value_drivers_from_prb(prb_drivers, top_k=5):
    if not prb_drivers: return [], []
    
    # 1. Aggregate scores
    by_pred = {}
    for d in prb_drivers:
        p = d["predictor"]
        if not p: continue
        if p not in by_pred: by_pred[p] = {"score": 0.0, "slope": d["slope"]}
        by_pred[p]["score"] += d["score"]

    # 2. Assign Groups
    def get_group(name):
        for g, vars_set in DRIVER_GROUPS.items():
            if name in vars_set: return g
        return "Other"

    # 3. Top K Drivers
    total_top = sum(v["score"] for k,v in sorted(by_pred.items(), key=lambda x: x[1]["score"], reverse=True)[:top_k]) or 1.0
    drivers = []
    for p, info in sorted(by_pred.items(), key=lambda x: x[1]["score"], reverse=True)[:top_k]:
        drivers.append({
            "predictor": p, "group": get_group(p),
            "importance": round(info["score"]/total_top, 3),
            "direction": "up" if info["slope"] < 0 else "down"
        })

    # 4. Group Aggregates
    grp_scores = {}
    for p, info in by_pred.items():
        g = get_group(p)
        grp_scores[g] = grp_scores.get(g, 0.0) + info["score"]
    
    total_grp = sum(grp_scores.values()) or 1.0
    groups = [{"group": g, "importance": round(s/total_grp, 3)} for g, s in sorted(grp_scores.items(), key=lambda x: x[1], reverse=True)]

    return groups, drivers

def diagnostics_for_segment(df, model, predictors, stats, mandatory=None):
    """Return a compact, human-readable summary for a market group × tier segment."""
    mandatory = list(mandatory or [])
    added_predictors = [p for p in predictors if p not in mandatory]
    
    ratio_series = df["ratio"]
    ratio_stats = {
        "skew": float(ratio_series.skew()),
        "kurt": float(ratio_series.kurt()),
        "p10": float(ratio_series.quantile(0.10)),
        "p50": float(ratio_series.quantile(0.50)),
        "p90": float(ratio_series.quantile(0.90)),
    }

    perf = {
        "n": int(stats.get("n", len(df))),
        "COD": float(stats.get("COD", float("nan"))),
        "PRD": float(stats.get("PRD", float("nan"))),
        "PRB": stats.get("PRB"),
        "median_ratio": float(stats.get("median_ratio", ratio_stats["p50"])),
        "r2": float(stats.get("r2", float("nan"))),
        "adj_r2": float(stats.get("adj_r2", float("nan")))
    }
    
    vif = {
        c: float(round(sm_influence.variance_inflation_factor(model.model.exog, i), 2))
        for i, c in enumerate(model.model.exog_names) if c != "const"
    }

    return {
        "segment": stats.get("label"),
        "market_group": stats.get("market_group"),
        "value_tier": stats.get("value_tier"),
        "performance": perf,
        "ratio_distribution": ratio_stats,
        "predictors": {
            "all": predictors,
            "mandatory": mandatory,
            "added": added_predictors,
        },
        "vif": vif,
        "drivers": {
            "value_drivers": stats.get("value_drivers", []),
            "driver_groups": stats.get("value_driver_groups", []),
            "prb_drivers": stats.get("PRB_drivers", []),
        },
        "calibration": {
            "bands": stats.get("calib_bands", []),
            "prb": stats.get("PRB_calibration"),
        }
    }
