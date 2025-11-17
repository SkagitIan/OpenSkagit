"""
Reporting helpers.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional


def summarize_iteration(metrics: Dict[str, float], recommendations: Optional[Iterable[str]] = None) -> str:
    """Produce short summary string for console streaming."""
    r2 = metrics.get("R2") or 0.0
    cod = metrics.get("COD") or 0.0
    prd = metrics.get("PRD") or 0.0
    n_obs = metrics.get("n_obs") or 0

    text = f"R²={r2:.3f}, COD={cod:.2f}, PRD={prd:.3f}, obs={n_obs}"
    if recommendations:
        text += "\nRecommendations:"
        for rec in recommendations:
            text += f"\n- {rec}"
    return text
