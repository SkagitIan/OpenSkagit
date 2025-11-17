"""
Dataset profiling helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any
import json

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = BASE_DIR / "outputs" / "data_profile.json"


def analyze_dataset(path: str = "data/sample_data.csv") -> Dict[str, Any]:
    """
    Inspect dataset for missing values, skew, and simple correlations.
    """
    csv_path = Path(path)
    if not csv_path.is_absolute():
        csv_path = BASE_DIR / path

    df = pd.read_csv(csv_path)
    profile = {
        "n_rows": int(len(df)),
        "missing_pct": df.isna().mean().round(3).to_dict(),
        "skewness": df.skew(numeric_only=True).round(2).to_dict(),
        "correlations": df.corr(numeric_only=True).round(2).to_dict(),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    return profile
