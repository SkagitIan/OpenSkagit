"""
Lightweight regression regression test harness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional

from regression_pipeline import run_pipeline

BASE_DIR = Path(__file__).resolve().parents[1]


def test_script(dataset_path: Optional[str] = None) -> Dict[str, Any]:
    """Execute regression pipeline and report success + metrics."""
    resolved_path = None
    if dataset_path:
        resolved = Path(dataset_path)
        if not resolved.is_absolute():
            resolved = BASE_DIR / resolved
        resolved_path = resolved

    try:
        metrics, _ = run_pipeline(data_path=resolved_path)
        return {"success": True, "metrics": metrics}
    except Exception as exc:  # pragma: no cover
        return {"success": False, "error": str(exc)}
