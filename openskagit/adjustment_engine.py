from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.db.models import Max

from .models import AdjustmentCoefficient

# Terms we store in the DB but do NOT expose as separate “adjustments”
IGNORED_TERMS = {"const", "missing_quality", "missing_condition"}
IGNORED_PREFIXES = ("pt_",)

# These must exist in AdjustmentCoefficient for a market group to be usable
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

# Keys we emit into the adjustments dict for each comparable
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

# Same anchor you used in the regression scripts
REGRESSION_ANCHOR_DATE = date(2015, 1, 1)

# Time-adjustment controls
# - coefficients' time term `t` is on a MONTHS scale (via _regression_time_value)
# - cap trending distance to avoid extreme extrapolation on stale sales
# - optional shrink allows taming adjustments if market cooled vs. long-run fit
TIME_CAP_MONTHS: float = 60.0
TIME_SHRINK: float = 1.0  # set < 1.0 (e.g., 0.6) to dampen time adjustments
INCLUDE_AREA_TIME_IN_TREND: bool = True  # incorporates `area_time` into time trending when present


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
    valuation_date = _get_valuation_date(subject)

    comparable_payloads: List[Dict[str, Any]] = []

    for idx, comp in enumerate(comps, start=1):
        base_price = _to_float(
            comp.get("sale_price")
            or comp.get("sale_price_raw")
            or comp.get("base_sale_price")
        )
        if base_price is None or base_price <= 0:
            # skip bad comp rows silently – UI already filters these upstream
            continue

        comp_features = _extract_features(comp)

        adjustments, adjustment_details = _build_adjustments(
            subject_features=subject_features,
            comp_features=comp_features,
            coefficients=coefficients,
            subject_pred_price=subject_price,
            base_sale_price=base_price,
            valuation_date=valuation_date,
        )

        total_adjustment = sum(adjustments.values())
        comp_id = (
            comp.get("comp_id")
            or comp.get("parcel_number")
            or comp.get("id")
            or f"comp_{idx}"
        )

        comparable_payloads.append(
            {
                "comp_id": str(comp_id),
                "base_sale_price": _currency(base_price),
                "adjustments": {key: _currency(value) for key, value in adjustments.items()},
                "adjustment_details": adjustment_details,
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
    base_sale_price: float,
    valuation_date: date,
) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
    """
    Build per-factor adjustments.

    - Area, lot, age, quality, condition, garage, basement, view:
      regression-based multiplicative adjustments applied to subject_pred_price.
    - Time:
      IAAO-style adjustment applied to base comp sale price, trending it
      from comp sale date to the valuation_date using the 't' coefficient.
    """
    adjustments: Dict[str, float] = {key: 0.0 for key in ADJUSTMENT_KEYS}
    adjustment_details: Dict[str, Dict[str, Any]] = {}

    def _record_detail(
        key: str,
        subject_value: Any,
        comp_value: Any,
        delta: Optional[float],
    ) -> None:
        adjustment_details[key] = {
            "delta": delta,
            "subject_value": subject_value,
            "comp_value": comp_value,
        }

    # AREA
    area_delta_value = _delta(subject_features.gla, comp_features.gla)
    adjustments["area"] = _multiplicative_adjustment(
        coefficients.get("log_area"),
        _delta(subject_features.log_area, comp_features.log_area),
        subject_pred_price,
    )
    _record_detail("area", subject_features.gla, comp_features.gla, area_delta_value)

    # LOT
    lot_delta_value = _delta(subject_features.lot_acres, comp_features.lot_acres)
    adjustments["lot"] = _multiplicative_adjustment(
        coefficients.get("log_lot"),
        _delta(subject_features.log_lot, comp_features.log_lot),
        subject_pred_price,
    )
    _record_detail("lot", subject_features.lot_acres, comp_features.lot_acres, lot_delta_value)

    # AGE
    age_delta_value = _delta(subject_features.age, comp_features.age)
    adjustments["age"] = _multiplicative_adjustment(
        coefficients.get("log_age"),
        _delta(subject_features.log_age, comp_features.log_age),
        subject_pred_price,
    )
    _record_detail("age", subject_features.age, comp_features.age, age_delta_value)

    # QUALITY
    quality_delta_value = _delta(subject_features.quality_score, comp_features.quality_score)
    adjustments["quality"] = _multiplicative_adjustment(
        coefficients.get("quality_score"),
        _delta(subject_features.quality_score, comp_features.quality_score),
        subject_pred_price,
    )
    _record_detail(
        "quality",
        subject_features.quality_score,
        comp_features.quality_score,
        quality_delta_value,
    )

    # CONDITION
    condition_delta_value = _delta(
        subject_features.condition_score,
        comp_features.condition_score,
    )
    adjustments["condition"] = _multiplicative_adjustment(
        coefficients.get("condition_score"),
        _delta(subject_features.condition_score, comp_features.condition_score),
        subject_pred_price,
    )
    _record_detail(
        "condition",
        subject_features.condition_score,
        comp_features.condition_score,
        condition_delta_value,
    )

    # GARAGE
    garage_delta_value = _delta(subject_features.has_garage, comp_features.has_garage)
    adjustments["garage"] = _multiplicative_adjustment(
        coefficients.get("has_garage"),
        _delta(subject_features.has_garage, comp_features.has_garage),
        subject_pred_price,
    )
    _record_detail("garage", subject_features.has_garage, comp_features.has_garage, garage_delta_value)

    # BASEMENT
    basement_delta_value = _delta(subject_features.has_basement, comp_features.has_basement)
    adjustments["basement"] = _multiplicative_adjustment(
        coefficients.get("has_basement"),
        _delta(subject_features.has_basement, comp_features.has_basement),
        subject_pred_price,
    )
    _record_detail(
        "basement",
        subject_features.has_basement,
        comp_features.has_basement,
        basement_delta_value,
    )

    # VIEW
    view_delta_value = _delta(subject_features.is_view, comp_features.is_view)
    adjustments["view"] = _multiplicative_adjustment(
        coefficients.get("is_view"),
        _delta(subject_features.is_view, comp_features.is_view),
        subject_pred_price,
    )
    _record_detail("view", subject_features.is_view, comp_features.is_view, view_delta_value)

    # TIME – IAAO-STYLE (use MONTHS on the regression scale)
    months = _months_between(valuation_date, comp_features.sale_date)
    adjustments["time"] = _time_adjustment(
        coefficients.get("t"),
        months,
        base_sale_price,
        beta_area_time=(coefficients.get("area_time") if INCLUDE_AREA_TIME_IN_TREND else None),
        log_area=comp_features.log_area,
    )
    _record_detail(
        "time",
        valuation_date.isoformat(),
        comp_features.sale_date.isoformat() if comp_features.sale_date else None,
        months,
    )

    return adjustments, adjustment_details


def _load_coefficients(
    market_group: str,
    *,
    run_id: Optional[str] = None,
    include_all_terms: bool = False,
) -> Tuple[Dict[str, float], Optional[str]]:
    qs = AdjustmentCoefficient.objects.filter(market_group=market_group)

    target_run = run_id
    if not target_run:
        target_run = (
            qs.values("run_id")
            .annotate(latest_created=Max("created_at"))
            .order_by("-latest_created")
            .values_list("run_id", flat=True)
            .first()
        )
    if not target_run:
        raise AdjustmentEngineError(f"No adjustment coefficients found for market_group={market_group}.")

    coeffs: Dict[str, float] = {}
    for coeff in qs.filter(run_id=target_run):
        term = coeff.term or ""
        if not include_all_terms and (term in IGNORED_TERMS or term.startswith(IGNORED_PREFIXES)):
            continue
        coeffs[term] = coeff.beta

    return coeffs, target_run


def _get_valuation_date(subject: Dict[str, Any]) -> date:
    """
    Pick a single valuation date for the grid.

    Priority:
      1) subject["valuation_date"] or subject["assessment_date"]
      2) Jan 1 of assessment_roll_year / roll_year if present
      3) today (fallback)
    """
    v = subject.get("valuation_date") or subject.get("assessment_date")
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v

    year = (
        subject.get("assessment_roll_year")
        or subject.get("roll_year")
        or subject.get("year")
    )
    if isinstance(year, int) and 1990 < year < 2100:
        return date(year, 1, 1)

    return date.today()


def _time_adjustment(
    beta_t: Optional[float],
    months: Optional[float],
    base_sale_price: float,
    *,
    beta_area_time: Optional[float] = None,
    log_area: Optional[float] = None,
) -> float:
    """
    IAAO-style time adjustment on the comp's base sale price.

    - `beta_t` is the regression time coefficient on a MONTH scale.
    - We trend from comp sale date to the valuation date by Δmonths.
    - Optionally include the area×time interaction so larger homes trend slightly
      differently when the model provides an `area_time` coefficient.
    """
    if beta_t is None or months is None or months == 0 or base_sale_price <= 0:
        return 0.0

    # cap extrapolation
    months = max(min(months, TIME_CAP_MONTHS), -TIME_CAP_MONTHS)

    effective_beta = beta_t
    if beta_area_time is not None and log_area is not None:
        effective_beta += beta_area_time * log_area

    # optional damping to avoid over-aggressive trending without refitting
    effective_beta *= TIME_SHRINK

    delta_log_price = effective_beta * months
    factor = math.exp(delta_log_price) - 1.0
    return base_sale_price * factor



def predict_price(
    payload: Dict[str, Any],
    *,
    market_group: str,
    run_id: Optional[str] = None,
) -> Optional[float]:
    """
    Predict a sale price directly from coefficients for a given market group.

    Used to generate the subject's `subject_pred_price` in your CMA flow.
    """
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

    # Core continuous features
    accumulate("log_area", features.log_area)
    accumulate("log_lot", features.log_lot)
    accumulate("log_age", features.log_age)

    # Quality / condition
    if features.quality_score is None:
        accumulate("missing_quality", 1.0)
    else:
        accumulate("quality_score", features.quality_score)

    if features.condition_score is None:
        accumulate("missing_condition", 1.0)
    else:
        accumulate("condition_score", features.condition_score)

    # Binary features
    accumulate("has_garage", float(features.has_garage) if features.has_garage is not None else None)
    accumulate("has_basement", float(features.has_basement) if features.has_basement is not None else None)
    accumulate("is_view", float(features.is_view) if features.is_view is not None else None)

    # Time index on the regression scale
    time_index = _regression_time_value(features.sale_date)
    accumulate("t", time_index)

    # Area × time interaction is used for prediction only (not displayed as a separate adjustment)
    if time_index is not None and features.log_area is not None:
        beta = coeffs.get("area_time")
        if beta is not None:
            log_price += beta * features.log_area * time_index

    # Property-type dummies (pt_*)
    pt_term = _property_type_term(payload.get("property_type"))
    if pt_term is not None and pt_term in coeffs:
        log_price += coeffs[pt_term]

    try:
        return float(math.exp(log_price))
    except (OverflowError, ValueError):
        return None


def _extract_features(payload: Dict[str, Any]) -> FeatureSnapshot:
    """Normalize raw CMA payload into a typed FeatureSnapshot."""
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
    """
    Dollarize a coefficient using the standard log-price adjustment:

        new_price = subject_pred_price * exp(beta * delta)

    We return the difference:

        adjustment = subject_pred_price * (exp(beta * delta) - 1)
    """
    if beta is None or delta is None or delta == 0:
        return 0.0
    delta_log_price = beta * delta
    factor = math.exp(delta_log_price) - 1
    return subject_pred_price * factor


def _delta(subject_value: Optional[float], comp_value: Optional[float]) -> Optional[float]:
    """
    Compute SUBJECT minus COMP for a given feature.

    This direction is intentional:

    - If the comp is superior on a feature (e.g., larger GLA),
      subject_value - comp_value will be negative and the adjustment
      will reduce the comp's indicated value.

    - If the comp is inferior (e.g., smaller GLA), the delta is positive
      and the adjustment will increase the comp's indicated value.
    """
    if subject_value is None or comp_value is None:
        return None
    return subject_value - comp_value


def _regression_time_value(target_date: Optional[date]) -> Optional[float]:
    if target_date is None:
        return None
    return (target_date - REGRESSION_ANCHOR_DATE).days / 30.4375


def _months_between(subject_date: Optional[date], comp_date: Optional[date]) -> Optional[float]:
    """Difference in the regression time index measured in MONTHS.

    This matches the scale used by `t` in the coefficient table and by
    `predict_price()` where we accumulate `t * time_index` directly.
    """
    subject_value = _regression_time_value(subject_date)
    comp_value = _regression_time_value(comp_date)
    if subject_value is None or comp_value is None:
        return None
    return subject_value - comp_value


def _years_between(subject_date: Optional[date], comp_date: Optional[date]) -> Optional[float]:
    if subject_date is None or comp_date is None:
        return None
    return (subject_date - comp_date).days / 365.25


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
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in (None, "", "null"):
        return None
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
