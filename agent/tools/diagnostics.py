"""
Metric helpers (COD + PRD).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]


def compute_cod_prd(df_path: str = "data/sample_data.csv") -> Dict[str, Any]:
    """Compute COD and PRD for dataset sample."""
    csv_path = Path(df_path)
    if not csv_path.is_absolute():
        csv_path = BASE_DIR / df_path

    df = pd.read_csv(csv_path)
    ratio = df["assessed_value"] / df["sale_price"]
    median = float(np.median(ratio))
    cod = float(np.mean(np.abs(ratio - median) / median) * 100)
    prd = float(np.mean(ratio) / median)
    return {"COD": round(cod, 2), "PRD": round(prd, 3), "median_ratio": round(median, 3)}
