from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from pydantic import BaseModel, Field


STATS_DIR = Path(settings.BASE_DIR) / "data" / "regression_stats"


class RegressionRunMetadata(BaseModel):
    run_id: str
    generated_at: str
    mode: str = "sfr"
    dataset: str = "sale_regression_sfr"
    market_group_col: str | None = None


class RegressionGlobalMetrics(BaseModel):
    total_observations: int = 0
    segments: int = 0
    market_groups: List[str] = Field(default_factory=list)
    cod: float | None = None
    prd: float | None = None
    prb: float | None = None
    rmse: float | None = None


class RegressionCoefficient(BaseModel):
    term: str
    beta: float
    beta_se: float | None = None


class RegressionCoefficientGroup(BaseModel):
    market_group: str
    display_name: str
    coefficients: List[RegressionCoefficient]


class RegressionSegmentDiagnostics(BaseModel):
    segment: str | None = None
    market_group: str | None = None
    value_tier: str | None = None
    performance: Dict[str, Any] = Field(default_factory=dict)
    ratio_distribution: Dict[str, Any] = Field(default_factory=dict)
    predictors: Dict[str, Any] = Field(default_factory=dict)
    vif: Dict[str, float] = Field(default_factory=dict)
    drivers: Dict[str, Any] = Field(default_factory=dict)
    calibration: Dict[str, Any] = Field(default_factory=dict)
    flags: List[str] = Field(default_factory=list)
    outliers: List[Dict[str, Any]] = Field(default_factory=list)
    time_trend: Dict[str, Any] | None = None
    errors: List[str] = Field(default_factory=list)

    class Config:
        extra = "allow"


class RegressionRunPayload(BaseModel):
    metadata: RegressionRunMetadata
    stats: List[Dict[str, Any]] = Field(default_factory=list)
    segments: List[RegressionSegmentDiagnostics] = Field(default_factory=list)
    coefficients: List[RegressionCoefficientGroup] = Field(default_factory=list)
    global_metrics: RegressionGlobalMetrics | None = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    class Config:
        extra = "allow"


def ensure_regression_stats_dir() -> Path:
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    return STATS_DIR


def write_regression_run_payload(payload: RegressionRunPayload) -> Path:
    ensure_regression_stats_dir()
    target = STATS_DIR / f"{payload.metadata.run_id}.json"
    target.write_text(json.dumps(payload.dict(), indent=2, default=str))
    return target


def _load_payload_from_path(path: Path) -> Optional[RegressionRunPayload]:
    try:
        raw = json.loads(path.read_text())
        return RegressionRunPayload.parse_obj(raw)
    except (json.JSONDecodeError, OSError):
        return None


def load_regression_run(run_id: str | None = None, mode: str | None = None) -> Tuple[Optional[RegressionRunPayload], Optional[Path]]:
    ensure_regression_stats_dir()

    if run_id:
        candidate = STATS_DIR / f"{run_id}.json"
        if not candidate.exists():
            return None, None
        payload = _load_payload_from_path(candidate)
        if payload and (mode is None or payload.metadata.mode == mode):
            return payload, candidate
        return None, None

    files = sorted(STATS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        payload = _load_payload_from_path(path)
        if not payload:
            continue
        if mode and payload.metadata.mode != mode:
            continue
        return payload, path

    return None, None


def list_regression_runs(mode: str | None = None) -> List[RegressionRunMetadata]:
    runs: List[RegressionRunMetadata] = []
    ensure_regression_stats_dir()
    files = sorted(STATS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        payload = _load_payload_from_path(path)
        if not payload:
            continue
        if mode and payload.metadata.mode != mode:
            continue
        runs.append(payload.metadata)
    return runs
