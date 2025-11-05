import json
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from statsmodels.stats.outliers_influence import variance_inflation_factor
from django.core.management.base import BaseCommand
from sqlalchemy import create_engine
from openskagit.models import RegressionAdjustment, RegressionResult, AssessmentRoll


class Command(BaseCommand):
    help = "Run regression analysis on sales data and store interpretable adjustment factors in RegressionAdjustment"

    def handle(self, *args, **options):
        engine = create_engine("postgresql://django:grandson2025@localhost:5432/skagit")

        query = """
        SELECT sale_price, sale_date, living_area, lot_acres, bedrooms, bathrooms,
               year_built, eff_year_built, condition_code, land_use_code,
               neighborhood_code, has_attached_garage, has_detached_garage
        FROM sale_regression_dataset
        WHERE sale_price BETWEEN 50000 AND 2000000
          AND living_area BETWEEN 400 AND 6000
          AND lot_acres < 10;
        """

        df = pd.read_sql(query, engine)
        results = self.run_regression(df)
        model = results["model"]

        adj_factors = self.interpret_coefficients(model.params.to_dict())

        # clear old data (optional)
        RegressionAdjustment.objects.all().delete()

        for var, pct in adj_factors.items():
            RegressionAdjustment.objects.create(
                variable=var,
                adjustment_pct=pct,
                model_version=f"2025Q4 | AdjR2={model.rsquared_adj:.3f}",
            )

        self.stdout.write(self.style.SUCCESS(f"✅ Saved {len(adj_factors)} regression adjustments."))

    # --------------------------------------------------------
    # Core regression logic
    # --------------------------------------------------------
    def run_regression(self, df: pd.DataFrame, min_neigh_n: int = 30, k_folds: int = 5):
        # --- numeric cleanup ---
        num_cols = [
            'sale_price','living_area','lot_acres','bedrooms','bathrooms',
            'year_built','eff_year_built','has_attached_garage','has_detached_garage'
        ]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')

        # --- categorical cleanup ---
        for c in ['condition_code','land_use_code','neighborhood_code']:
            if c not in df.columns:
                continue
            df[c] = df[c].astype(str).str.strip().replace("", "Unknown")
            vc = df[c].value_counts()
            rare = vc[vc < 20].index
            df.loc[df[c].isin(rare), c] = 'Other'

        # --- feature engineering ---
        df['sale_date'] = pd.to_datetime(df['sale_date'], errors='coerce')
        df['months_since_2015'] = (df['sale_date'] - pd.Timestamp('2015-01-01')).dt.days / 30
        df['log_price'] = np.log(df['sale_price'])
        df['log_area'] = np.log(df['living_area'].clip(lower=0.0001))
        df['log_lot'] = np.log(df['lot_acres'].clip(lower=0.0001))
        df['effective_age'] = (df['eff_year_built'] - df['year_built']).clip(lower=0)
        df['months_sq'] = df['months_since_2015'] ** 2

        for g in ['has_attached_garage','has_detached_garage']:
            df[g] = df.get(g, 0).fillna(0).astype(int)

        if 'neighborhood_code' in df.columns:
            vc = df['neighborhood_code'].value_counts()
            big = set(vc[vc >= min_neigh_n].index)
            df.loc[~df['neighborhood_code'].isin(big), 'neighborhood_code'] = 'Other'

        df = pd.get_dummies(
            df,
            columns=['neighborhood_code','condition_code','land_use_code'],
            drop_first=True
        )

        predictors = [
            'log_area','log_lot','bedrooms','bathrooms',
            'months_since_2015','months_sq','effective_age',
            'has_attached_garage','has_detached_garage'
        ]
        predictors += [c for c in df.columns if c.startswith(('neighborhood_code_','condition_code_','land_use_code_'))]

        X = df[predictors].replace([np.inf, -np.inf], np.nan)
        y = df['log_price']
        mask = X.notna().all(axis=1) & y.notna()
        X, y = X[mask], y[mask]

        # --- scale continuous predictors only ---
        cont = ['log_area','log_lot','bedrooms','bathrooms','months_since_2015','months_sq','effective_age']
        scaler = StandardScaler()
        X[cont] = scaler.fit_transform(X[cont])

        X = sm.add_constant(X, has_constant='add')
        X = X.apply(pd.to_numeric, errors='coerce').astype(float)
        y = pd.to_numeric(y, errors='coerce').astype(float)

        # --- fit model ---
        model = sm.OLS(y, X).fit(cov_type="HC3")

        # --- drop outliers by Cook’s distance ---
        cooks = model.get_influence().cooks_distance[0]
        keep = cooks < (4 / len(X))
        model_refit = sm.OLS(y[keep], X[keep]).fit(cov_type="HC3")

        # --- cross-validation ---
        kf = KFold(n_splits=k_folds, shuffle=True, random_state=42)
        r2_scores = []
        for train_idx, test_idx in kf.split(X):
            m = sm.OLS(y.iloc[train_idx], X.iloc[train_idx]).fit()
            preds = m.predict(X.iloc[test_idx])
            r2_scores.append(r2_score(y.iloc[test_idx], preds))
        cv_r2 = np.mean(r2_scores)

        print(f"Adj R²: {model_refit.rsquared_adj:.3f} | Mean CV R²: {cv_r2:.3f}")
        return {"model": model_refit}

    # --------------------------------------------------------
    # Interpret coefficients into % adjustments
    # --------------------------------------------------------
    def interpret_coefficients(self, coefs: dict):
        adj_factors = {}
        for k, v in coefs.items():
            if k == "const" or pd.isna(v) or abs(v) > 5:
                continue
            try:
                pct = (np.exp(v) - 1) * 100
            except Exception:
                pct = v * 100
            adj_factors[k] = round(float(pct), 4)
        return dict(sorted(adj_factors.items()))
