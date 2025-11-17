"""
Regression runner tool wrapping regression_pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional

from regression_pipeline import run_pipeline

BASE_DIR = Path(__file__).resolve().parents[1]


def run_regression(dataset_path: Optional[str] = None) -> Dict[str, Any]:
    """Run regression and return summary metrics."""
    resolved_path = None
    if dataset_path:
        resolved = Path(dataset_path)
        if not resolved.is_absolute():
            resolved = BASE_DIR / resolved
        resolved_path = resolved

    results, details = run_pipeline(data_path=resolved_path)
    metrics = {
        "R2": results.get("R2"),
        "COD": results.get("COD"),
        "PRD": results.get("PRD"),
        "n_obs": results.get("n_obs"),
        "timestamp": results.get("timestamp"),
    }
    metrics["settings"] = details.get("settings")
    return metrics
