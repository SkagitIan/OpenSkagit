"""
Lightweight regression pipeline used by the agent prototype.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import datetime as dt

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = BASE_DIR / "data" / "sample_data.csv"

# BEGIN_MODEL_SETTINGS
MODEL_SETTINGS: Dict[str, Any] = {
    "poly_degree": 1,
    "include_quality": True,
    "include_interactions": False,
    "interaction_weight": 1.0,
    "ridge_alpha": 0.0,
}
# END_MODEL_SETTINGS


def _resolve_path(data_path: Optional[Path]) -> Path:
    if data_path:
        return data_path
    return DEFAULT_DATA_PATH


def _build_features(df: pd.DataFrame, settings: Dict[str, Any]) -> Tuple[np.ndarray, List[str]]:
    columns: List[str] = []
    mats: List[np.ndarray] = []

    base_cols = ["living_area", "lot_size", "bedrooms", "bathrooms"]
    for col in base_cols:
        columns.append(col)
        mats.append(df[col].to_numpy(dtype=float))

    if settings.get("include_quality", True):
        columns.append("quality_score")
        mats.append(df["quality_score"].to_numpy(dtype=float))

    if settings.get("poly_degree", 1) >= 2:
        columns.append("living_area_sq")
        mats.append((df["living_area"] ** 2).to_numpy(dtype=float))

    if settings.get("include_interactions"):
        weight = float(settings.get("interaction_weight", 1.0))
        columns.append("living_area_quality")
        mats.append((df["living_area"] * df["quality_score"] * weight).to_numpy(dtype=float))

    matrix = np.column_stack(mats)
    return matrix, columns


def _fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    eye = np.eye(X.shape[1])
    regularizer = eye * alpha
    beta = np.linalg.solve(X.T @ X + regularizer, X.T @ y)
    return beta


def _compute_metrics(df: pd.DataFrame, predictions: np.ndarray) -> Dict[str, float]:
    ratios = (df["assessed_value"].to_numpy(dtype=float) / predictions).clip(0.1, 5.0)
    median_ratio = float(np.median(ratios))
    cod = float(np.mean(np.abs(ratios - median_ratio) / median_ratio) * 100)
    high = ratios[ratios >= median_ratio]
    low = ratios[ratios < median_ratio]
    prd = float(np.mean(high) / np.mean(low)) if len(low) else float("inf")

    residuals = df["sale_price"].to_numpy(dtype=float) - predictions
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((df["sale_price"] - df["sale_price"].mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

    return {"COD": round(cod, 2), "PRD": round(prd, 3), "R2": round(r2, 3), "median_ratio": round(median_ratio, 3)}


def run_pipeline(*, data_path: Optional[Path] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    csv_path = _resolve_path(data_path)
    df = pd.read_csv(csv_path)

    settings = dict(MODEL_SETTINGS)
    X, columns = _build_features(df, settings)

    y = df["sale_price"].to_numpy(dtype=float)
    X_with_intercept = np.column_stack([np.ones(len(df)), X])

    ridge_alpha = float(settings.get("ridge_alpha", 0.0))
    coefs = _fit_ridge(X_with_intercept, y, ridge_alpha)
    predictions = X_with_intercept @ coefs

    metrics = _compute_metrics(df, predictions)
    metrics.update(
        {
            "n_obs": len(df),
            "timestamp": dt.datetime.utcnow().isoformat(),
        }
    )

    coef_map = {"intercept": round(coefs[0], 4)}
    for idx, name in enumerate(columns, start=1):
        coef_map[name] = round(coefs[idx], 6)

    details = {"settings": settings, "coefficients": coef_map}
    return metrics, details


if __name__ == "__main__":  # pragma: no cover
    metrics, details = run_pipeline()
    print("Metrics:", metrics)
    print("Settings:", details["settings"])
