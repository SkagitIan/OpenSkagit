from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import AdjustmentCoefficient

IGNORED_TERMS = {"const", "missing_quality", "missing_condition"}
IGNORED_PREFIXES = ("pt_",)
REQUIRED_TERMS = {
    "log_area",
    "log_lot",
    "log_age",
    "t",
    "quality_score",
    "condition_score",
    "has_garage",
    "has_basement",
    "is_view",
}
ADJUSTMENT_KEYS = (
    "area",
    "lot",
    "age",
    "quality",
    "condition",
    "garage",
    "basement",
    "view",
    "time",
)

REGRESSION_ANCHOR_DATE = date(2015, 1, 1)


class AdjustmentEngineError(Exception):
    """Base exception for the adjustment engine."""


class MissingCoefficientError(AdjustmentEngineError):
    """Raised when a required coefficient is unavailable."""

    def __init__(self, missing_terms: Iterable[str], market_group: str, run_id: Optional[str]) -> None:
        terms = ", ".join(sorted(missing_terms))
        message = f"Missing coefficient(s) [{terms}] for market_group={market_group} (run_id={run_id or 'latest'})."
        super().__init__(message)
        self.missing_terms = tuple(missing_terms)
        self.market_group = market_group
        self.run_id = run_id


@dataclass
class FeatureSnapshot:
    gla: Optional[float]
    log_area: Optional[float]
    lot_acres: Optional[float]
    log_lot: Optional[float]
    age: Optional[float]
    log_age: Optional[float]
    quality_score: Optional[float]
    condition_score: Optional[float]
    has_garage: Optional[int]
    has_basement: Optional[int]
    is_view: Optional[int]
    sale_date: Optional[date]


def compute_adjustments(
    *,
    subject: Dict[str, Any],
    comps: Iterable[Dict[str, Any]],
    subject_pred_price: Any,
    market_group: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply regression-derived adjustments to comparable sales so each comp
    reflects the subject property as if it shared the same characteristics.
    """

    if subject_pred_price is None:
        raise AdjustmentEngineError("subject_pred_price is required.")

    subject_price = _to_float(subject_pred_price)
    if subject_price is None or subject_price <= 0:
        raise AdjustmentEngineError("subject_pred_price must be a positive number.")

    group = market_group or subject.get("valuation_area") or subject.get("market_group")
    if not group:
        raise AdjustmentEngineError("Market group / valuation_area is required for the subject.")

    coefficients, resolved_run_id = _load_coefficients(group, run_id=run_id)
    missing_terms = [term for term in REQUIRED_TERMS if term not in coefficients]
    if missing_terms:
        raise MissingCoefficientError(missing_terms, group, resolved_run_id)

    subject_features = _extract_features(subject)
    comparable_payloads: List[Dict[str, Any]] = []

    for idx, comp in enumerate(comps or [], start=1):
        if not isinstance(comp, dict):
            continue
        comp_features = _extract_features(comp)
        base_price = _to_float(comp.get("sale_price")) or 0.0
        adjustments = _build_adjustments(
            subject_features=subject_features,
            comp_features=comp_features,
            coefficients=coefficients,
            subject_pred_price=subject_price,
        )
        total_adjustment = sum(adjustments.values())
        comp_id = comp.get("comp_id") or comp.get("parcel_number") or comp.get("id") or f"comp_{idx}"
        comparable_payloads.append(
            {
                "comp_id": str(comp_id),
                "base_sale_price": _currency(base_price),
                "adjustments": {key: _currency(value) for key, value in adjustments.items()},
                "total_adjustment": _currency(total_adjustment),
                "adjusted_value": _currency(base_price + total_adjustment),
            }
        )

    return {
        "subject_pred_price": _currency(subject_price),
        "market_group": group,
        "comparables": comparable_payloads,
    }


def _build_adjustments(
    *,
    subject_features: FeatureSnapshot,
    comp_features: FeatureSnapshot,
    coefficients: Dict[str, float],
    subject_pred_price: float,
) -> Dict[str, float]:
    adjustments = {key: 0.0 for key in ADJUSTMENT_KEYS}

    adjustments["area"] = _multiplicative_adjustment(
        coefficients.get("log_area"),
        _delta(subject_features.log_area, comp_features.log_area),
        subject_pred_price,
    )
    adjustments["lot"] = _multiplicative_adjustment(
        coefficients.get("log_lot"),
        _delta(subject_features.log_lot, comp_features.log_lot),
        subject_pred_price,
    )
    adjustments["age"] = _multiplicative_adjustment(
        coefficients.get("log_age"),
        _delta(subject_features.log_age, comp_features.log_age),
        subject_pred_price,
    )

    adjustments["quality"] = _multiplicative_adjustment(
        coefficients.get("quality_score"),
        _delta(subject_features.quality_score, comp_features.quality_score),
        subject_pred_price,
    )
    adjustments["condition"] = _multiplicative_adjustment(
        coefficients.get("condition_score"),
        _delta(subject_features.condition_score, comp_features.condition_score),
        subject_pred_price,
    )

    adjustments["garage"] = _multiplicative_adjustment(
        coefficients.get("has_garage"),
        _delta(subject_features.has_garage, comp_features.has_garage),
        subject_pred_price,
    )
    adjustments["basement"] = _multiplicative_adjustment(
        coefficients.get("has_basement"),
        _delta(subject_features.has_basement, comp_features.has_basement),
        subject_pred_price,
    )
    adjustments["view"] = _multiplicative_adjustment(
        coefficients.get("is_view"),
        _delta(subject_features.is_view, comp_features.is_view),
        subject_pred_price,
    )

    months = _months_between(subject_features.sale_date, comp_features.sale_date)
    adjustments["time"] = _multiplicative_adjustment(coefficients.get("t"), months, subject_pred_price)

    return adjustments


def _load_coefficients(
    market_group: str, *, run_id: Optional[str] = None, include_all_terms: bool = False
) -> Tuple[Dict[str, float], Optional[str]]:
    qs = AdjustmentCoefficient.objects.filter(market_group=market_group)
    target_run = run_id
    if not target_run:
        target_run = qs.order_by("-created_at").values_list("run_id", flat=True).first()
    if not target_run:
        raise AdjustmentEngineError(f"No adjustment coefficients found for market_group={market_group}.")

    coeffs: Dict[str, float] = {}
    for coeff in qs.filter(run_id=target_run):
        term = coeff.term or ""
        if not include_all_terms and (term in IGNORED_TERMS or term.startswith(IGNORED_PREFIXES)):
            continue
        coeffs[term] = coeff.beta
    return coeffs, target_run


def predict_price(
    payload: Dict[str, Any],
    *,
    market_group: str,
    run_id: Optional[str] = None,
) -> Optional[float]:
    coeffs, _ = _load_coefficients(market_group, run_id=run_id, include_all_terms=True)
    if not coeffs:
        return None

    features = _extract_features(payload)
    log_price = coeffs.get("const", 0.0)

    def accumulate(term: str, value: Optional[float]) -> None:
        nonlocal log_price
        if value is None:
            return
        beta = coeffs.get(term)
        if beta is None:
            return
        log_price += beta * value

    accumulate("log_area", features.log_area)
    accumulate("log_lot", features.log_lot)
    accumulate("log_age", features.log_age)

    if features.quality_score is None:
        accumulate("missing_quality", 1.0)
    else:
        accumulate("quality_score", features.quality_score)

    if features.condition_score is None:
        accumulate("missing_condition", 1.0)
    else:
        accumulate("condition_score", features.condition_score)

    accumulate("has_garage", float(features.has_garage) if features.has_garage is not None else None)
    accumulate("has_basement", float(features.has_basement) if features.has_basement is not None else None)
    accumulate("is_view", float(features.is_view) if features.is_view is not None else None)

    time_index = _regression_time_value(features.sale_date)
    accumulate("t", time_index)

    if time_index is not None and features.log_area is not None:
        beta = coeffs.get("area_time")
        if beta is not None:
            log_price += beta * features.log_area * time_index

    pt_term = _property_type_term(payload.get("property_type"))
    if pt_term is not None and pt_term in coeffs:
        log_price += coeffs[pt_term]

    try:
        return float(math.exp(log_price))
    except (OverflowError, ValueError):
        return None


def _extract_features(payload: Dict[str, Any]) -> FeatureSnapshot:
    gla = _to_float(payload.get("GLA") or payload.get("gla") or payload.get("living_area"))
    if gla is not None and gla <= 0:
        gla = None
    lot_acres = _to_float(payload.get("lot_acres"))
    if lot_acres is not None and lot_acres < 0:
        lot_acres = None
    age = _to_float(payload.get("age"))
    if age is not None and age < 0:
        age = None

    return FeatureSnapshot(
        gla=gla,
        log_area=math.log(gla) if gla else None,
        lot_acres=lot_acres,
        log_lot=math.log(1 + lot_acres) if lot_acres is not None else None,
        age=age,
        log_age=math.log(1 + age) if age is not None else None,
        quality_score=_to_float(payload.get("quality_score")),
        condition_score=_to_float(payload.get("condition_score")),
        has_garage=_to_flag(payload.get("has_garage")),
        has_basement=_to_flag(payload.get("has_basement")),
        is_view=_to_flag(payload.get("is_view")),
        sale_date=_parse_date(payload.get("sale_date") or payload.get("effective_date")),
    )


def _multiplicative_adjustment(beta: Optional[float], delta: Optional[float], subject_pred_price: float) -> float:
    if beta is None or delta is None or delta == 0:
        return 0.0
    delta_log_price = beta * delta
    factor = math.exp(delta_log_price) - 1
    return subject_pred_price * factor


def _delta(subject_value: Optional[float], comp_value: Optional[float]) -> Optional[float]:
    if subject_value is None or comp_value is None:
        return None
    return comp_value - subject_value


def _regression_time_value(target_date: Optional[date]) -> Optional[float]:
    if target_date is None:
        return None
    return (target_date - REGRESSION_ANCHOR_DATE).days / 30.4375


def _months_between(subject_date: Optional[date], comp_date: Optional[date]) -> Optional[float]:
    subject_value = _regression_time_value(subject_date)
    comp_value = _regression_time_value(comp_date)
    if subject_value is None or comp_value is None:
        return None
    return comp_value - subject_value


def _currency(value: float) -> float:
    return round(float(value), 2)


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_flag(value: Any) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return 1 if num >= 1 else 0


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromisoformat(text).date()
            except ValueError:
                return None
    return None


def _property_type_term(raw_value: Any) -> Optional[str]:
    if raw_value in (None, "", "null"):
        return None
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError):
        try:
            numeric = float(str(raw_value).strip())
        except (TypeError, ValueError):
            return None
    if numeric.is_integer():
        numeric = int(numeric)
        return f"pt_{numeric}.0"
    return f"pt_{numeric}"
