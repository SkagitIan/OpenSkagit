"""
Simple SQL facade that loads the sample CSV into an in-memory SQLite table.
Only SELECT statements are permitted; at most 5 rows are returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Dict, Optional
import sqlite3

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BASE_DIR / "data" / "sample_data.csv"


def run_sql_query(query: str, *, dataset_path: Optional[str] = None) -> List[Dict[str, Any]]:
    query_lower = query.strip().lower()
    if not query_lower.startswith("select"):
        raise ValueError("Only SELECT queries are permitted.")
    forbidden = ["update", "delete", "insert", "drop", "alter"]
    if any(keyword in query_lower for keyword in forbidden):
        raise ValueError("Unsafe SQL detected.")

    csv_path = Path(dataset_path) if dataset_path else DEFAULT_DATASET
    if not csv_path.is_absolute():
        csv_path = BASE_DIR / csv_path

    df = pd.read_csv(csv_path)

    with sqlite3.connect(":memory:") as conn:
        df.to_sql("sales", conn, index=False, if_exists="replace")
        cursor = conn.execute(query)
        columns = [col[0] for col in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(5)

    return [dict(zip(columns, row)) for row in rows]
