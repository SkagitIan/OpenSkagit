# openskagit/management/commands/build_adjustment_coefficients.py

import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from openskagit.models import AdjustmentCoefficient, AdjustmentRunSummary


class Command(BaseCommand):
    """
    Build regression-based adjustment coefficients per market group
    (valuation_area) and store them in AdjustmentCoefficient.

    Flow:
      - Load sale_regression_sfr view via Django connection.
      - For each valuation_area, run the regression with:
          * P10–P95 sale_price trimming
          * 1–99% trims on living_area and lot_acres
          * log_area, log_lot, log_age, t, area_time
          * quality_score, condition_score, is_view, has_garage, has_basement
          * price-tier dummies
      - Compute COD / PRD / median ratio for diagnostics.
      - Insert one row per (market_group, term, run_id) into AdjustmentCoefficient.

    Also supports:
      - --undo: delete coefficients for the latest run_id (or a specific run_id).
    """

    help = "Run adjustment regressions per market group and store coefficients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--market-group-col",
            type=str,
            default="valuation_area",
            help="Column name to group markets on (default: valuation_area).",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="Optional run_id override; default is current timestamp.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run analysis but do not write AdjustmentCoefficient rows.",
        )
        parser.add_argument(
            "--undo",
            action="store_true",
            help="Undo the last coefficient run (or a specific run_id if provided).",
        )

    # -------------------------
    # Undo helper
    # -------------------------
    def handle_undo(self, run_id: str | None):
        """
        Delete AdjustmentCoefficient rows for the given run_id.
        If run_id is None, find the most recent run_id by created_at.
        """
        qs = AdjustmentCoefficient.objects.all()

        if run_id:
            target_run_id = run_id
        else:
            # Get the run_id of the most recently created coefficient
            last = qs.order_by("-created_at").values_list("run_id", flat=True).first()
            if not last:
                self.stdout.write(self.style.WARNING("No coefficients found to undo."))
                return
            target_run_id = last

        to_delete = qs.filter(run_id=target_run_id)
        count = to_delete.count()

        if count == 0:
            self.stdout.write(
                self.style.WARNING(f"No coefficients found for run_id={target_run_id}.")
            )
            return

        with transaction.atomic():
            to_delete.delete()

        self.stdout.write(
            self.style.WARNING(
                f"Deleted {count} AdjustmentCoefficient rows for run_id={target_run_id}."
            )
        )

    # -------------------------
    # Core regression function
    # -------------------------
    def run_adjustment_model(self, df: pd.DataFrame, label: str, group_col: str | None):
        """
        Lightweight adjustment model:
        - Restricts to plausible sales
        - Trims sale_price to P10–P95; living_area and lot_acres to 1–99%
        - Drops obvious luxury tail inside that range
        - Returns (summary_dict, model, diag_df) or None
        """
        if len(df) < 75:
            self.stdout.write(f"{label}: too few rows ({len(df)}), skipping.")
            return None

        df = df.copy()

        # ------------------------------
        # BASIC CLEAN FILTERS
        # ------------------------------
        df = df.dropna(subset=["sale_price", "living_area", "lot_acres", "age"])
        df = df[df["sale_price"] > 50000]

        # Aggressive trim on price (10–95%) to drop bargain bin + luxury tail
        # Softer trim on area/lot just to kill true outliers.
        p_lo, p_hi = df["sale_price"].quantile([0.05, 0.95])
        a_lo, a_hi = df["living_area"].quantile([0.02, 0.98])
        l_lo, l_hi = df["lot_acres"].quantile([0.02, 0.98])

        df = df[
            df["sale_price"].between(p_lo, p_hi)
            & df["living_area"].between(a_lo, a_hi)
            & df["lot_acres"].between(l_lo, l_hi)
        ]

        # Hard caps on area
        df = df[df["living_area"].between(450, 6000)]

        df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
        df = df[df["sale_date"].notna()]

        if len(df) < 50:
            self.stdout.write(f"{label}: not enough rows after cleaning, skipping.")
            return None

        # ------------------------------
        # CORE TRANSFORMS
        # ------------------------------
        df["log_area"] = np.log(df["living_area"])
        df["log_lot"] = np.log1p(df["lot_acres"].clip(lower=0))
        df["log_age"] = np.log1p(df["age"].clip(lower=0))
        df["log_area_sq"] = df["log_area"] ** 2

        # Time trend – MUST stay in sync with adjustment engine
        REGRESSION_ANCHOR_DATE = pd.Timestamp("2015-01-01")
        df["t"] = (df["sale_date"] - REGRESSION_ANCHOR_DATE).dt.days / 30.4375
        df["t_sq"] = df["t"] ** 2

        # Interaction: bigger homes might trend differently
        df["area_time"] = df["log_area"] * df["t"]
        df["area_quality"] = df["log_area"] * df["quality_score"]
        df["area_condition"] = df["log_area"] * df["condition_score"]


        # Quality / Condition handling (from Assessor scores)
        median_q = df["quality_score"].median()
        median_c = df["condition_score"].median()

        df["missing_quality"] = df["quality_score"].isna().astype(int)
        df["missing_condition"] = df["condition_score"].isna().astype(int)

        df["quality_score"] = df["quality_score"].fillna(median_q)
        df["condition_score"] = df["condition_score"].fillna(median_c)

                # ------------------------------------------
        # QUALITY BAND (Low, Mid, High)
        # ------------------------------------------
        df["quality_band"] = pd.cut(
            df["quality_score"],
            bins=[-1, 2, 3, 10],   # (0-2)=Low, 3=Mid, 4-10=High
            labels=["LOW", "MID", "HIGH"]
        )
        quality_dummies = pd.get_dummies(
            df["quality_band"], prefix="qb", drop_first=True, dtype=float
        )
        df = df.join(quality_dummies)


        # ------------------------------
        # VIEW FLAG (from SQL view)
        # ------------------------------
        if "is_view" not in df.columns:
            raise ValueError("Expected 'is_view' column from sale_regression_sfr view")
        df["is_view"] = df["is_view"].fillna(0).astype(int)

        # ------------------------------------------------------------
        #  Correct luxury removal (Skagit-appropriate, IAAO compliant)
        # ------------------------------------------------------------

        # Remove only the true extreme luxury sales
        lux_cut = df["sale_price"].quantile(0.985)

        df = df[df["sale_price"] < lux_cut]

        # Very large houses can distort slope; light trim only
        df = df[df["living_area"] < 5500]

        # Light waterfront-only removal: only the top 0.5% of WF sales
        if "valuation_subarea" in df.columns:
            wf = df["valuation_subarea"] == "WATERFRONT"
            wf_cut = df.loc[wf, "sale_price"].quantile(0.995)
            df = df[~(wf & (df["sale_price"] >= wf_cut))]


        # ------------------------------
        # PREDICTORS
        # ------------------------------
        predictors = [
            "log_area", "log_area_sq",
            "log_lot",
            "log_age",
            "t", "t_sq",
            "area_time",
            "quality_score", "condition_score",
            "area_quality","area_condition",
            "has_garage", "has_basement",
            "missing_quality", "missing_condition",
            "is_view",
        ]

        predictors.extend(quality_dummies.columns.tolist())

        # price-tier dummies
        #predictors.extend(pt_dummies.columns.tolist())

        # Optional within-group dummies (e.g. neighborhood_code) – skipped here
        if group_col:
            counts = df[group_col].value_counts()
            replace_small = counts[counts < 10].index
            df[group_col] = df[group_col].replace(replace_small, "OTHER")

            dummies = pd.get_dummies(
                df[group_col], prefix=group_col, drop_first=True, dtype=float
            )
            df = df.join(dummies)
            predictors.extend(dummies.columns.tolist())

        # Final NA / constant cleanup
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=predictors)

        nunique = df[predictors].nunique()
        keep = [c for c in predictors if nunique[c] > 1]

        if not keep:
            self.stdout.write(f"{label}: all predictors constant, skipping.")
            return None

        X = sm.add_constant(df[keep])
        y = np.log(df["sale_price"])

        # Fit robust OLS
        model = sm.OLS(y, X).fit(cov_type="HC3")

        # Predictions + smearing
        df["pred_ln"] = model.predict(X)
        df["pred"] = np.exp(df["pred_ln"])
        smear = np.exp(model.resid).mean()
        df["pred"] *= smear

        df["ratio"] = df["sale_price"] / df["pred"]

        med = df["ratio"].median()
        cod = (np.abs(df["ratio"] - med) / med).median() * 100

        upper = df["ratio"][df["ratio"] >= med]
        lower = df["ratio"][df["ratio"] < med]
        prd = upper.mean() / lower.mean() if len(upper) and len(lower) else None

        summary = {
            "label": label,
            "n": int(len(df)),
            "r2": float(model.rsquared),
            "adj_r2": float(model.rsquared_adj),
            "COD": float(round(cod, 2)),
            "PRD": float(round(prd, 3)) if prd is not None else None,
            "median_ratio": float(round(med, 3)),
        }

        return summary, model, df

    # -------------------------
    # Main entry point
    # -------------------------
    def handle(self, *args, **options):
        market_group_col = options["market_group_col"]
        run_id = options["run_id"] or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        dry_run = options["dry_run"]
        undo = options["undo"]

        # If undo flag: perform undo and bail out
        if undo:
            self.handle_undo(options.get("run_id"))
            return

        self.stdout.write(self.style.SUCCESS(f"Starting adjustment build, run_id={run_id}"))

        # Load from materialized view using Django connection
        self.stdout.write("Loading sale_regression_sfr from database…")
        df = pd.read_sql_query("SELECT * FROM sale_regression_sfr", connection)
        self.stdout.write(f"Loaded {len(df)} rows.")

        if market_group_col not in df.columns:
            raise ValueError(f"market_group_col '{market_group_col}' not in dataframe columns.")

        adjustment_results = []
        coef_rows = []

        # Run model per market group (valuation_area)
        for group, subdf in df.groupby(market_group_col):
            label = f"ADJ_{group}"
            self.stdout.write(f"\n=== {label} ===")

            res = self.run_adjustment_model(subdf, label, group_col=None)
            if not res:
                continue

            summary, model, diag_df = res
            adjustment_results.append(summary)

            # Extract coefficients
            params = model.params
            bse = model.bse

            for term, beta in params.items():
                coef_rows.append(
                    AdjustmentCoefficient(
                        market_group=str(group),
                        term=str(term),
                        beta=float(beta),
                        beta_se=float(bse.get(term, np.nan)),
                        run_id=run_id,
                    )
                )

            # Print quick summary for this group
            prd_str = f"{summary['PRD']:.3f}" if summary["PRD"] is not None else "NA"
            self.stdout.write(
                f"n={summary['n']}, R²={summary['r2']:.3f}, "
                f"adj_R²={summary['adj_r2']:.3f}, COD={summary['COD']:.2f}, "
                f"PRD={prd_str}, median_ratio={summary['median_ratio']:.3f}"
            )

        # Print overall summary table
        if adjustment_results:
            self.stdout.write("\n=== SUMMARY (by market group) ===")
            cols = ["label", "n", "r2", "adj_r2", "COD", "PRD", "median_ratio"]
            header = ",".join(cols)
            self.stdout.write(header)
            for row in adjustment_results:
                line = ",".join(str(row[c]) for c in cols)
                self.stdout.write(line)
        else:
            self.stdout.write(self.style.WARNING("No successful models built; nothing to write."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled; not writing coefficients."))
            return

        # Write coefficients in one transaction
        self.stdout.write(f"\nWriting {len(coef_rows)} coefficients to AdjustmentCoefficient…")
        with transaction.atomic():
            AdjustmentRunSummary.objects.update_or_create(
                run_id=run_id,
                defaults={"stats": adjustment_results},
            )
            AdjustmentCoefficient.objects.bulk_create(coef_rows, batch_size=1000)

        self.stdout.write(self.style.SUCCESS("✅ Adjustment coefficients written successfully."))
