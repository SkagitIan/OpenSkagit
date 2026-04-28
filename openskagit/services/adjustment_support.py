from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from django.contrib.gis.geos import GEOSGeometry

from openskagit import cma
from openskagit.models import MasterParcel, ParcelGeometry, Sales
from openskagit.services.sales_comps import build_sales_comps_v2


MODEL_VERSION = "adjustment_support_v1"
SFR_LAND_USE_CODES = {"110", "111", "112"}
DEFAULT_MONTHS_LOOKBACK = 24
DEFAULT_MIN_SAMPLE_TARGET = 30
MAX_MONTHS_LOOKBACK = 120
RIDGE_ALPHA = 1.0
EXPANDED_MIN_SAMPLE_TARGET = 60

IAAO_LEVEL_LOW = 0.90
IAAO_LEVEL_HIGH = 1.10
IAAO_PRD_LOW = 0.98
IAAO_PRD_HIGH = 1.03
IAAO_MIN_SAMPLE_SIZE = 5

TRUST_HIGH_MIN = 75
TRUST_MEDIUM_MIN = 50
FORCED_LOW_TRUST_MONTHS = 120


@dataclass
class MarketContext:
    subject_land_use_code: Optional[str]
    subject_property_type: Optional[str]
    subject_neighborhood_code: Optional[str]
    subject_city_district: Optional[str]
    subject_market_group: Optional[str]
    comp_neighborhood_codes: List[str]
    comp_city_districts: List[str]
    comp_market_groups: List[str]


@dataclass
class SampleSelection:
    rows: List[Dict[str, Any]]
    months_used: int
    geography_level: str
    strategy_label: str
    attempts: List[Dict[str, Any]]


@dataclass
class FitResult:
    status: str
    coefficients: Dict[str, float]
    variables_used: List[str]
    diagnostics: Dict[str, Any]
    suppression_reasons: List[str]
    warnings: List[str]
    subject_predicted_price: Optional[float]


def build_adjustment_support_v1(
    subject: cma.PropertySnapshot,
    *,
    valuation_date: Optional[dt.date] = None,
    months_lookback: Optional[int] = None,
    min_sample_target: Optional[int] = None,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Experimental support analysis for adjustment hints.

    Core principle:
    - Comps pick the market.
    - Regression estimates adjustment support hints.
    """

    as_of_date = _resolve_valuation_date(subject, valuation_date)
    normalized_months = _normalize_months(months_lookback)
    sample_target = _normalize_sample_target(min_sample_target)

    subject_summary = _subject_summary(subject, as_of_date)
    warnings: List[str] = []

    if subject_summary.get("land_use_code") not in SFR_LAND_USE_CODES:
        trust = _build_trust_assessment(
            status="suppressed",
            months_used=None,
            geography_level=None,
            widening_steps=[],
            warnings=["unsupported_subject_class"],
            iaao_compliance=None,
            retry_used=False,
            reduced_variable_set_used=False,
        )
        payload = {
            "model_version": MODEL_VERSION,
            "status": "suppressed",
            "not_enough_sales": False,
            "suppressed": True,
            "suppression_reason": "unsupported_subject_class",
            "subject": subject_summary,
            "regression_sample_size": 0,
            "months_used": None,
            "geography_context": None,
            "market_context": None,
            "market_area": None,
            "variables_used": [],
            "coefficient_estimates": {},
            "suggested_adjustment_hints": [],
            "model_quality": {},
            "iaao_metrics": _empty_iaao_metrics(),
            "iaao_compliance": _empty_iaao_compliance(),
            "warnings": ["adjustment_support_v1 currently supports SFR land-use codes 110/111/112 only."],
            "trust_state": trust["trust_state"],
            "trust_score": trust["trust_score"],
            "trust_reasons": trust["trust_reasons"],
            "widening_steps": [],
        }
        if debug:
            payload["debug"] = {"as_of_date": as_of_date.isoformat()}
        return payload

    try:
        market_context = _resolve_market_context(subject)
    except Exception as exc:
        return _error_payload(
            subject_summary=subject_summary,
            warnings=warnings,
            error_message=f"market_context_failed: {exc}",
        )

    try:
        sample = _build_regression_sample_with_fallbacks(
            subject=subject,
            market_context=market_context,
            as_of_date=as_of_date,
            initial_months=normalized_months,
            min_sample_target=sample_target,
        )
    except Exception as exc:
        return _error_payload(
            subject_summary=subject_summary,
            warnings=warnings,
            error_message=f"sample_selection_failed: {exc}",
            market_context=_serialize_market_context(market_context),
        )

    best_size = len(sample.rows)
    widening_steps = _build_widening_steps(
        sample.attempts,
        final_level=sample.geography_level,
        final_months=sample.months_used,
        final_count=best_size,
    )
    market_area = _build_market_area(sample.rows)
    iaao_metrics, iaao_compliance, iaao_warnings = _compute_iaao_metrics_from_rows(
        sample.rows,
        property_type=(subject.property_type or "R"),
    )
    warnings.extend(iaao_warnings)

    if best_size < sample_target:
        warnings.append(
            f"Not enough sales after fallback steps (found {best_size}, need {sample_target})."
        )
        trust = _build_trust_assessment(
            status="not_enough_sales",
            months_used=sample.months_used,
            geography_level=sample.geography_level,
            widening_steps=widening_steps,
            warnings=warnings,
            iaao_compliance=iaao_compliance,
            retry_used=False,
            reduced_variable_set_used=False,
        )
        payload = {
            "model_version": MODEL_VERSION,
            "status": "not_enough_sales",
            "not_enough_sales": True,
            "suppressed": False,
            "suppression_reason": None,
            "subject": subject_summary,
            "regression_sample_size": best_size,
            "months_used": sample.months_used,
            "geography_context": {
                "level": sample.geography_level,
                "strategy": sample.strategy_label,
            },
            "market_context": _serialize_market_context(market_context),
            "market_area": market_area,
            "variables_used": [],
            "coefficient_estimates": {},
            "suggested_adjustment_hints": [],
            "model_quality": {},
            "iaao_metrics": iaao_metrics,
            "iaao_compliance": iaao_compliance,
            "warnings": warnings,
            "trust_state": trust["trust_state"],
            "trust_score": trust["trust_score"],
            "trust_reasons": trust["trust_reasons"],
            "widening_steps": widening_steps,
        }
        if debug:
            payload["debug"] = {
                "as_of_date": as_of_date.isoformat(),
                "attempts": sample.attempts,
            }
        return payload

    try:
        fit_result = _fit_adjustment_model(
            subject=subject,
            as_of_date=as_of_date,
            rows=sample.rows,
            min_sample_target=sample_target,
        )
    except Exception as exc:
        return _error_payload(
            subject_summary=subject_summary,
            warnings=warnings,
            error_message=f"model_fit_failed: {exc}",
            market_context=_serialize_market_context(market_context),
            market_area=_build_market_area(sample.rows),
            sample=sample,
        )

    if fit_result.status == "suppressed" and _should_retry_with_expanded_context(
        fit_result.suppression_reasons
    ):
        expanded_target = max(sample_target, EXPANDED_MIN_SAMPLE_TARGET)
        try:
            expanded_sample = _build_regression_sample_with_fallbacks(
                subject=subject,
                market_context=market_context,
                as_of_date=as_of_date,
                initial_months=max(normalized_months, 36),
                min_sample_target=expanded_target,
                prefer_broader=True,
            )
            if len(expanded_sample.rows) > len(sample.rows):
                warnings.append(
                    "Initial model was unstable; retried with expanded time/geography context."
                )
                retry_fit = _fit_adjustment_model(
                    subject=subject,
                    as_of_date=as_of_date,
                    rows=expanded_sample.rows,
                    min_sample_target=sample_target,
                )
                sample = expanded_sample
                fit_result = retry_fit
        except Exception:
            warnings.append(
                "Expanded-context retry failed; continuing with initial suppression result."
            )
    widening_steps = _build_widening_steps(
        sample.attempts,
        final_level=sample.geography_level,
        final_months=sample.months_used,
        final_count=len(sample.rows),
    )
    retry_used = any(
        "expanded time/geography context" in str(item).lower()
        for item in warnings
    )
    warnings.extend(fit_result.warnings)

    coeffs = fit_result.coefficients if fit_result.status == "ready" else {}
    hints = (
        _build_adjustment_hints(
            coefficients=fit_result.coefficients,
            rows=sample.rows,
        )
        if fit_result.status == "ready"
        else []
    )

    suppression_reason = None
    if fit_result.status == "suppressed":
        suppression_reason = ", ".join(fit_result.suppression_reasons) or "quality_checks_failed"
        warnings.append(
            "Adjustment hints were suppressed because model quality/sanity checks did not pass."
        )

    reduced_variable_set_used = any(
        str(warning).startswith("Reduced variable set for stability:")
        for warning in warnings
    )
    trust = _build_trust_assessment(
        status=fit_result.status,
        months_used=sample.months_used,
        geography_level=sample.geography_level,
        widening_steps=widening_steps,
        warnings=warnings,
        iaao_compliance=iaao_compliance,
        retry_used=retry_used,
        reduced_variable_set_used=reduced_variable_set_used,
    )

    payload = {
        "model_version": MODEL_VERSION,
        "status": fit_result.status,
        "not_enough_sales": False,
        "suppressed": fit_result.status == "suppressed",
        "suppression_reason": suppression_reason,
        "subject": subject_summary,
        "regression_sample_size": len(sample.rows),
        "months_used": sample.months_used,
        "geography_context": {
            "level": sample.geography_level,
            "strategy": sample.strategy_label,
        },
        "market_context": _serialize_market_context(market_context),
        "market_area": market_area,
        "variables_used": fit_result.variables_used,
        "coefficient_estimates": coeffs,
        "suggested_adjustment_hints": hints,
        "model_quality": fit_result.diagnostics,
        "iaao_metrics": iaao_metrics,
        "iaao_compliance": iaao_compliance,
        "warnings": warnings,
        "trust_state": trust["trust_state"],
        "trust_score": trust["trust_score"],
        "trust_reasons": trust["trust_reasons"],
        "widening_steps": widening_steps,
    }
    if debug:
        payload["debug"] = {
            "as_of_date": as_of_date.isoformat(),
            "attempts": sample.attempts,
            "suppression_reasons": fit_result.suppression_reasons,
            "all_coefficients": fit_result.coefficients,
        }
    return payload


def _resolve_market_context(subject: cma.PropertySnapshot) -> MarketContext:
    canonical = build_sales_comps_v2(subject, limit=15, months=18)
    subject_meta = _metadata_dict(subject)

    comp_hoods: List[str] = []
    comp_cities: List[str] = []
    comp_groups: List[str] = []
    for comp in canonical.comparables:
        snap = getattr(comp, "snapshot", None)
        if not snap:
            continue
        meta = _metadata_dict(snap)
        hood = _norm_text(meta.get("neighborhood_code"))
        city = _norm_text(meta.get("city_district"))
        grp = _norm_text(meta.get("valuation_area"))
        if hood:
            comp_hoods.append(hood)
        if city:
            comp_cities.append(city)
        if grp:
            comp_groups.append(grp)

    return MarketContext(
        subject_land_use_code=_norm_text(subject_meta.get("land_use_code")),
        subject_property_type=_norm_text(subject.property_type),
        subject_neighborhood_code=_norm_text(subject_meta.get("neighborhood_code")),
        subject_city_district=_norm_text(subject_meta.get("city_district")),
        subject_market_group=_norm_text(subject_meta.get("valuation_area")),
        comp_neighborhood_codes=sorted(set(comp_hoods)),
        comp_city_districts=sorted(set(comp_cities)),
        comp_market_groups=sorted(set(comp_groups)),
    )


def _build_regression_sample_with_fallbacks(
    *,
    subject: cma.PropertySnapshot,
    market_context: MarketContext,
    as_of_date: dt.date,
    initial_months: int,
    min_sample_target: int,
    prefer_broader: bool = False,
) -> SampleSelection:
    hood_codes = set(market_context.comp_neighborhood_codes)
    if market_context.subject_neighborhood_code:
        hood_codes.add(market_context.subject_neighborhood_code)

    city_codes = set(market_context.comp_city_districts)
    if market_context.subject_city_district:
        city_codes.add(market_context.subject_city_district)

    attempts: List[Dict[str, Any]] = []

    month_candidates = sorted(
        {
            min(MAX_MONTHS_LOOKBACK, max(1, int(initial_months))),
            36,
            60,
            84,
            120,
        }
    )

    strategies: List[Tuple[str, int, Dict[str, Any]]] = []
    if hood_codes and not prefer_broader:
        for months in month_candidates[:2]:
            strategies.append(("comp_neighborhood", months, {"hood_codes": sorted(hood_codes)}))
    if city_codes:
        city_months = month_candidates if prefer_broader else month_candidates[1:]
        for months in city_months:
            strategies.append(("city_district", months, {"city_codes": sorted(city_codes)}))
    for months in month_candidates[2:]:
        strategies.append(("county_sfr", months, {}))

    best_rows: List[Dict[str, Any]] = []
    best_months = initial_months
    best_level = strategies[0][0]
    best_label = strategies[0][0]

    for level, months, geo in strategies:
        capped_months = min(MAX_MONTHS_LOOKBACK, max(1, int(months)))
        rows = _query_regression_rows(
            as_of_date=as_of_date,
            months_lookback=capped_months,
            hood_codes=geo.get("hood_codes"),
            city_codes=geo.get("city_codes"),
            exclude_parcel=_norm_text(subject.parcel_number),
        )
        attempts.append(
            {
                "strategy": level,
                "months": capped_months,
                "count": len(rows),
                "hood_codes": geo.get("hood_codes") or [],
                "city_codes": geo.get("city_codes") or [],
            }
        )
        if len(rows) > len(best_rows):
            best_rows = rows
            best_months = capped_months
            best_level = level
            best_label = level
        if len(rows) >= min_sample_target:
            return SampleSelection(
                rows=rows,
                months_used=capped_months,
                geography_level=level,
                strategy_label=level,
                attempts=attempts,
            )

    return SampleSelection(
        rows=best_rows,
        months_used=best_months,
        geography_level=best_level,
        strategy_label=best_label,
        attempts=attempts,
    )


def _query_regression_rows(
    *,
    as_of_date: dt.date,
    months_lookback: int,
    hood_codes: Optional[Sequence[str]] = None,
    city_codes: Optional[Sequence[str]] = None,
    exclude_parcel: Optional[str] = None,
) -> List[Dict[str, Any]]:
    cutoff_start = as_of_date - dt.timedelta(days=int(round(months_lookback * 30.4375)))

    parcel_qs = MasterParcel.objects.filter(
        proptype__iexact="R",
        land_use_code__in=SFR_LAND_USE_CODES,
    )
    if hood_codes:
        parcel_qs = parcel_qs.filter(hood_code__in=list(hood_codes))
    elif city_codes:
        parcel_qs = parcel_qs.filter(city_district__in=list(city_codes))

    parcel_rows = list(
        parcel_qs.values(
            "parcel_number",
            "hood_code",
            "city_district",
            "land_use_code",
            "proptype",
            "final_living_area",
            "total_living_area",
            "living_area",
            "final_eff_yr_blt",
            "effective_yr_blt",
            "eff_year_built",
            "final_year_built",
            "year_built",
            "final_garage_area",
            "total_garage_area",
            "garagesqft",
            "acres",
            "total_market_value",
            "assessed_value",
            "quality_score",
            "condition_score",
            "building_style",
            "buildingstyle",
            "land_use_description",
        )
    )
    if not parcel_rows:
        return []

    parcel_map: Dict[str, Dict[str, Any]] = {}
    raw_parcels: List[str] = []
    for row in parcel_rows:
        pn_raw = row.get("parcel_number")
        pn = _norm_text(pn_raw)
        if not pn:
            continue
        parcel_map[pn] = row
        raw_parcels.append(str(pn_raw).strip())
    if not parcel_map:
        return []

    sales_qs = (
        Sales.objects.filter(
            sale_type__iregex=r"^\s*valid sale\s*$",
            sale_price__gt=0,
            sale_date__isnull=False,
            parcel_number__in=raw_parcels,
            sale_date__date__gte=cutoff_start,
            sale_date__date__lte=as_of_date,
        )
        .order_by("parcel_number", "-sale_date", "-id")
        .values("parcel_number", "sale_price", "sale_date")
    )

    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    for sale in sales_qs:
        pn = _norm_text(sale.get("parcel_number"))
        if not pn or pn in seen:
            continue
        if exclude_parcel and pn == exclude_parcel:
            continue
        parcel = parcel_map.get(pn)
        if not parcel:
            continue
        sale_price = _safe_float(sale.get("sale_price"))
        if sale_price is None or sale_price <= 0:
            continue
        sale_dt = sale.get("sale_date")
        if isinstance(sale_dt, dt.datetime):
            sale_date = sale_dt.date()
        elif isinstance(sale_dt, dt.date):
            sale_date = sale_dt
        else:
            continue

        feature_row = _build_feature_row(
            parcel=parcel,
            sale_price=sale_price,
            sale_date=sale_date,
            as_of_date=as_of_date,
        )
        if feature_row is None:
            continue
        seen.add(pn)
        rows.append(feature_row)
    return rows


def _build_feature_row(
    *,
    parcel: Dict[str, Any],
    sale_price: float,
    sale_date: dt.date,
    as_of_date: dt.date,
) -> Optional[Dict[str, Any]]:
    gla = _first_float(
        parcel.get("final_living_area"),
        parcel.get("total_living_area"),
        parcel.get("living_area"),
    )
    if gla is None or gla <= 0:
        return None

    year = _first_int(
        parcel.get("final_eff_yr_blt"),
        parcel.get("effective_yr_blt"),
        parcel.get("eff_year_built"),
        parcel.get("final_year_built"),
        parcel.get("year_built"),
    )
    if year is None:
        return None

    effective_age = max(as_of_date.year - year, 0)
    garage_area = _first_float(
        parcel.get("final_garage_area"),
        parcel.get("total_garage_area"),
        parcel.get("garagesqft"),
    )
    has_garage = 1.0 if (garage_area is not None and garage_area > 0) else 0.0

    acres = _safe_float(parcel.get("acres"))
    if acres is None or acres < 0:
        return None
    log_lot_acres = math.log1p(acres)
    months_since_sale = max((as_of_date - sale_date).days / 30.4375, 0.0)

    assessed_value = _first_float(parcel.get("total_market_value"), parcel.get("assessed_value"))

    return {
        "parcel_number": _norm_text(parcel.get("parcel_number")),
        "sale_price": sale_price,
        "assessed_value": assessed_value,
        "sale_date": sale_date,
        "gla": gla,
        "effective_age": float(effective_age),
        "has_garage": has_garage,
        "log_lot_acres": log_lot_acres,
        "months_since_sale": months_since_sale,
    }


def _fit_adjustment_model(
    *,
    subject: cma.PropertySnapshot,
    as_of_date: dt.date,
    rows: Sequence[Dict[str, Any]],
    min_sample_target: int,
) -> FitResult:
    warnings: List[str] = []
    candidate_vars = ["gla", "effective_age", "has_garage", "log_lot_acres", "months_since_sale"]

    selected_vars: List[str] = []
    total_rows = len(rows)
    for name in candidate_vars:
        values = [row.get(name) for row in rows if row.get(name) is not None]
        coverage = (len(values) / total_rows) if total_rows else 0.0
        std_dev = statistics.pstdev(values) if len(values) >= 2 else 0.0
        if coverage >= 0.75 and std_dev > 1e-9:
            selected_vars.append(name)

    if "months_since_sale" not in selected_vars:
        return FitResult(
            status="suppressed",
            coefficients={},
            variables_used=[],
            diagnostics={},
            suppression_reasons=["time_term_missing_or_no_variation"],
            warnings=["Time term could not be estimated due to weak variation in sale dates."],
            subject_predicted_price=None,
        )

    if "gla" not in selected_vars:
        return FitResult(
            status="suppressed",
            coefficients={},
            variables_used=[],
            diagnostics={},
            suppression_reasons=["gla_missing_or_no_variation"],
            warnings=["Living area variation was too weak for adjustment support."],
            subject_predicted_price=None,
        )

    model_rows = [row for row in rows if all(row.get(v) is not None for v in selected_vars)]
    if len(model_rows) < min_sample_target:
        return FitResult(
            status="suppressed",
            coefficients={},
            variables_used=[],
            diagnostics={},
            suppression_reasons=["post_filter_sample_too_small"],
            warnings=[
                f"Only {len(model_rows)} rows remained after variable completeness filtering."
            ],
            subject_predicted_price=None,
        )

    fit_stats = _fit_and_score(model_rows, selected_vars)
    if not fit_stats:
        return FitResult(
            status="suppressed",
            coefficients={},
            variables_used=[],
            diagnostics={},
            suppression_reasons=["regression_numerical_failure"],
            warnings=["Regression failed numerically."],
            subject_predicted_price=None,
        )

    cond = fit_stats["condition_number"]
    if cond is not None and cond > 5000:
        candidate_sets: List[List[str]] = []
        for remove_name in ("log_lot_acres", "effective_age", "has_garage"):
            reduced = [name for name in selected_vars if name != remove_name]
            if (
                len(reduced) >= 2
                and "gla" in reduced
                and "months_since_sale" in reduced
                and reduced not in candidate_sets
            ):
                candidate_sets.append(reduced)
        for reduced in (
            [name for name in ("gla", "months_since_sale", "effective_age") if name in selected_vars],
            [name for name in ("gla", "months_since_sale") if name in selected_vars],
        ):
            if len(reduced) >= 2 and reduced not in candidate_sets:
                candidate_sets.append(reduced)

        for candidate_vars in candidate_sets:
            candidate_stats = _fit_and_score(model_rows, candidate_vars)
            if not candidate_stats:
                continue
            candidate_cond = candidate_stats["condition_number"]
            if candidate_cond is None:
                continue
            if candidate_cond <= 5000 or candidate_cond < (cond * 0.5):
                fit_stats = candidate_stats
                selected_vars = list(candidate_vars)
                cond = candidate_cond
                warnings.append(
                    f"Reduced variable set for stability: {', '.join(candidate_vars)}."
                )
                break

    coefficients = fit_stats["coefficients"]
    r2 = fit_stats["r2"]
    mape = fit_stats["mape"]
    mdape = fit_stats["mdape"]
    intercept = fit_stats["intercept"]
    suppression_reasons = _sanity_checks(coefficients, r2=r2, mape=mape, condition_number=cond)
    stability_reasons = _split_sample_stability_checks(
        rows=model_rows,
        selected_vars=selected_vars,
        full_coefficients=coefficients,
    )
    suppression_reasons.extend(stability_reasons)
    if stability_reasons:
        warnings.append(
            "Coefficient stability check flagged substantial drift across split samples."
        )

    subject_features = _subject_feature_values(subject, as_of_date)
    subject_predicted_price = _predict_subject_price(intercept, coefficients, subject_features, selected_vars)

    diagnostics = {
        "ridge_alpha": RIDGE_ALPHA,
        "r2_log_price": _round_or_none(r2, 4),
        "mape": _round_or_none(mape, 4),
        "mdape": _round_or_none(mdape, 4),
        "condition_number": _round_or_none(cond, 2),
        "subject_predicted_sale_price": _round_or_none(subject_predicted_price, 0),
    }

    status = "suppressed" if suppression_reasons else "ready"
    return FitResult(
        status=status,
        coefficients=coefficients,
        variables_used=selected_vars,
        diagnostics=diagnostics,
        suppression_reasons=suppression_reasons,
        warnings=warnings,
        subject_predicted_price=subject_predicted_price,
    )


def _fit_ridge_log_model(
    X: np.ndarray,
    y: np.ndarray,
    *,
    alpha: float,
) -> Tuple[np.ndarray, float, np.ndarray]:
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds = np.where(stds == 0, 1.0, stds)
    z = (X - means) / stds

    z_i = np.column_stack([np.ones(len(z)), z])
    penalty = np.eye(z_i.shape[1], dtype=float)
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(z_i.T @ z_i + alpha * penalty, z_i.T @ y)

    coef_std = beta[1:]
    intercept_std = beta[0]

    coefs = coef_std / stds
    intercept = intercept_std - float(np.sum(coef_std * means / stds))
    y_hat = intercept + X @ coefs
    return coefs, intercept, y_hat


def _fit_and_score(
    rows: Sequence[Dict[str, Any]],
    variables: Sequence[str],
) -> Optional[Dict[str, Any]]:
    if not rows or not variables:
        return None
    try:
        X = np.array([[float(row[v]) for v in variables] for row in rows], dtype=float)
        y = np.array([math.log(float(row["sale_price"])) for row in rows], dtype=float)
        coeffs, intercept, y_hat = _fit_ridge_log_model(X, y, alpha=RIDGE_ALPHA)
    except Exception:
        return None

    y_hat_price = np.exp(y_hat)
    actual_price = np.exp(y)
    r2 = _r2_score(y, y_hat)
    mape = _mean_abs_pct_error(actual_price, y_hat_price)
    mdape = _median_abs_pct_error(actual_price, y_hat_price)
    cond = float(np.linalg.cond(X)) if X.size else None

    return {
        "coefficients": {name: float(coeffs[idx]) for idx, name in enumerate(variables)},
        "intercept": float(intercept),
        "r2": r2,
        "mape": mape,
        "mdape": mdape,
        "condition_number": cond,
    }


def _build_adjustment_hints(
    *,
    coefficients: Dict[str, float],
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not rows:
        return []
    sale_prices = [float(row["sale_price"]) for row in rows if row.get("sale_price")]
    if not sale_prices:
        return []
    base_price = float(statistics.median(sale_prices))

    hints: List[Dict[str, Any]] = []

    def _dollar_effect(beta: Optional[float], delta: float = 1.0) -> Optional[float]:
        if beta is None:
            return None
        return base_price * (math.exp(beta * delta) - 1.0)

    gla_effect = _dollar_effect(coefficients.get("gla"), 1.0)
    if gla_effect is not None:
        hints.append(
            {
                "factor": "living_area",
                "unit": "per_sqft",
                "estimate": _round_or_none(gla_effect, 0),
                "text": f"Living area contribution appears to be approximately ${_format_abs(gla_effect)} per sq ft.",
            }
        )

    garage_effect = _dollar_effect(coefficients.get("has_garage"), 1.0)
    if garage_effect is not None:
        direction = "adds" if garage_effect >= 0 else "reduces"
        hints.append(
            {
                "factor": "garage",
                "unit": "binary",
                "estimate": _round_or_none(garage_effect, 0),
                "text": f"Garage contribution appears to {direction} value by about ${_format_abs(garage_effect)}.",
            }
        )

    age_effect = _dollar_effect(coefficients.get("effective_age"), 1.0)
    if age_effect is not None:
        hints.append(
            {
                "factor": "effective_age",
                "unit": "per_year",
                "estimate": _round_or_none(age_effect, 0),
                "text": f"Effective age effect appears to be about ${_format_abs(age_effect)} per year.",
            }
        )

    time_effect = _dollar_effect(coefficients.get("months_since_sale"), 1.0)
    if time_effect is not None:
        hints.append(
            {
                "factor": "time",
                "unit": "per_month",
                "estimate": _round_or_none(time_effect, 0),
                "text": f"Time trend appears to move value by roughly ${_format_abs(time_effect)} per month.",
            }
        )

    return hints


def _compute_iaao_metrics_from_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    property_type: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    ratios: List[float] = []
    sales: List[float] = []
    assessed_values: List[float] = []
    log_prices: List[float] = []
    warnings: List[str] = []

    for row in rows:
        sale_price = _safe_float(row.get("sale_price"))
        assessed = _safe_float(row.get("assessed_value"))
        if sale_price is None or assessed is None or sale_price <= 0 or assessed <= 0:
            continue
        ratio = assessed / sale_price
        ratios.append(ratio)
        sales.append(sale_price)
        assessed_values.append(assessed)
        try:
            log_prices.append(math.log(sale_price))
        except Exception:
            pass

    sample_size = len(ratios)
    if sample_size == 0:
        return _empty_iaao_metrics(), _empty_iaao_compliance(), ["No valid ratio observations found."]

    median_ratio = statistics.median(ratios)
    mean_ratio = statistics.fmean(ratios)
    weighted_mean_ratio = (sum(assessed_values) / sum(sales)) if sum(sales) > 0 else None

    cod = None
    if median_ratio > 0:
        abs_deviation_median = statistics.median(abs(value - median_ratio) for value in ratios)
        cod = (abs_deviation_median / median_ratio) * 100.0

    prd = None
    if weighted_mean_ratio and weighted_mean_ratio > 0:
        prd = mean_ratio / weighted_mean_ratio

    prb = _compute_prb(log_prices, ratios)
    ci_low, ci_high = _mean_confidence_interval(ratios)

    cod_low, cod_high = (5.0, 15.0) if (property_type or "").upper() == "R" else (5.0, 20.0)
    level_ok = IAAO_LEVEL_LOW <= median_ratio <= IAAO_LEVEL_HIGH
    cod_ok = cod is not None and cod_low <= cod <= cod_high
    prd_ok = prd is not None and IAAO_PRD_LOW <= prd <= IAAO_PRD_HIGH
    sample_size_ok = sample_size >= IAAO_MIN_SAMPLE_SIZE
    sales_chasing_suspect = cod is not None and cod < 5.0 and sample_size >= 30

    if sample_size < IAAO_MIN_SAMPLE_SIZE:
        warnings.append("IAAO caution: fewer than 5 valid ratios in analysis set.")
    if cod is not None and cod < 5.0:
        warnings.append("COD below 5 can indicate over-smoothing or potential sales chasing.")
    if not level_ok:
        warnings.append("Median level falls outside IAAO 0.90-1.10 target range.")
    if prd is not None and not prd_ok:
        warnings.append("PRD falls outside IAAO 0.98-1.03 target range.")

    iaao_metrics = {
        "sample_size": sample_size,
        "median_ratio": _round_or_none(median_ratio, 4),
        "mean_ratio": _round_or_none(mean_ratio, 4),
        "weighted_mean_ratio": _round_or_none(weighted_mean_ratio, 4),
        "cod": _round_or_none(cod, 3),
        "prd": _round_or_none(prd, 4),
        "prb": _round_or_none(prb, 4),
        "mean_ratio_ci_95_lower": _round_or_none(ci_low, 4),
        "mean_ratio_ci_95_upper": _round_or_none(ci_high, 4),
    }
    iaao_compliance = {
        "level_ok": level_ok,
        "cod_ok": cod_ok,
        "prd_ok": prd_ok,
        "sample_size_ok": sample_size_ok,
        "sales_chasing_suspect": sales_chasing_suspect,
        "targets": {
            "level_low": IAAO_LEVEL_LOW,
            "level_high": IAAO_LEVEL_HIGH,
            "cod_low": cod_low,
            "cod_high": cod_high,
            "prd_low": IAAO_PRD_LOW,
            "prd_high": IAAO_PRD_HIGH,
            "min_sample_size": IAAO_MIN_SAMPLE_SIZE,
        },
    }
    return iaao_metrics, iaao_compliance, warnings


def _subject_feature_values(subject: cma.PropertySnapshot, as_of_date: dt.date) -> Dict[str, Optional[float]]:
    metadata = _metadata_dict(subject)
    gla = _first_float(subject.living_area, metadata.get("calculated_square_footage"))
    year = _first_int(subject.effective_year_built, subject.year_built)
    effective_age = None
    if year is not None:
        effective_age = float(max(as_of_date.year - year, 0))
    garage_sqft = _first_float(subject.garage_sqft)
    has_garage = None
    if garage_sqft is not None:
        has_garage = 1.0 if garage_sqft > 0 else 0.0
    elif "has_garage" in metadata:
        has_garage = 1.0 if bool(metadata.get("has_garage")) else 0.0

    acres = _first_float(subject.acres, subject.lot_acres, metadata.get("lot_acres"))
    log_lot = None
    if acres is not None and acres >= 0:
        log_lot = math.log1p(acres)

    sale_date = subject.sale_date or as_of_date
    months_since_sale = max((as_of_date - sale_date).days / 30.4375, 0.0)

    return {
        "gla": gla,
        "effective_age": effective_age,
        "has_garage": has_garage,
        "log_lot_acres": log_lot,
        "months_since_sale": months_since_sale,
    }


def _predict_subject_price(
    intercept: float,
    coefficients: Dict[str, float],
    subject_features: Dict[str, Optional[float]],
    selected_vars: Sequence[str],
) -> Optional[float]:
    total = intercept
    for var in selected_vars:
        value = subject_features.get(var)
        coeff = coefficients.get(var)
        if value is None or coeff is None:
            return None
        total += coeff * float(value)
    try:
        return float(math.exp(total))
    except Exception:
        return None


def _sanity_checks(
    coefficients: Dict[str, float],
    *,
    r2: Optional[float],
    mape: Optional[float],
    condition_number: Optional[float],
) -> List[str]:
    reasons: List[str] = []

    gla_beta = coefficients.get("gla")
    if gla_beta is not None and gla_beta < -0.0002:
        reasons.append("gla_sign_sanity_failed")

    garage_beta = coefficients.get("has_garage")
    if garage_beta is not None and garage_beta < -0.08:
        reasons.append("garage_sign_sanity_failed")

    age_beta = coefficients.get("effective_age")
    if age_beta is not None and abs(age_beta) > 0.05:
        reasons.append("age_effect_unstable")

    time_beta = coefficients.get("months_since_sale")
    if time_beta is not None and abs(time_beta) > 0.05:
        reasons.append("time_term_unstable")

    if r2 is not None and r2 < 0.05:
        reasons.append("model_fit_too_weak")
    if mape is not None and mape > 0.35:
        reasons.append("prediction_error_too_high")
    if condition_number is not None and condition_number > 5000:
        reasons.append("design_matrix_ill_conditioned")
    return reasons


def _split_sample_stability_checks(
    *,
    rows: Sequence[Dict[str, Any]],
    selected_vars: Sequence[str],
    full_coefficients: Dict[str, float],
) -> List[str]:
    if len(rows) < 24:
        return []

    sorted_rows = sorted(rows, key=lambda row: row.get("sale_date") or dt.date.min)
    midpoint = len(sorted_rows) // 2
    first_half = sorted_rows[:midpoint]
    second_half = sorted_rows[midpoint:]
    if len(first_half) < 10 or len(second_half) < 10:
        return []

    first_coeffs = _fit_coefficients_for_rows(first_half, selected_vars)
    second_coeffs = _fit_coefficients_for_rows(second_half, selected_vars)
    if not first_coeffs or not second_coeffs:
        return []

    reasons: List[str] = []

    gla_1 = first_coeffs.get("gla")
    gla_2 = second_coeffs.get("gla")
    if (
        gla_1 is not None
        and gla_2 is not None
        and gla_1 * gla_2 < 0
        and abs(gla_1) > 0.0001
        and abs(gla_2) > 0.0001
    ):
        reasons.append("gla_split_stability_failed")

    garage_1 = first_coeffs.get("has_garage")
    garage_2 = second_coeffs.get("has_garage")
    if (
        garage_1 is not None
        and garage_2 is not None
        and garage_1 * garage_2 < 0
        and abs(garage_1) > 0.03
        and abs(garage_2) > 0.03
    ):
        reasons.append("garage_split_stability_failed")

    time_full = full_coefficients.get("months_since_sale")
    time_1 = first_coeffs.get("months_since_sale")
    time_2 = second_coeffs.get("months_since_sale")
    if (
        time_full is not None
        and time_1 is not None
        and time_2 is not None
        and abs(time_1 - time_2) > max(0.01, abs(time_full) * 3.0)
    ):
        reasons.append("time_split_stability_failed")

    return reasons


def _fit_coefficients_for_rows(
    rows: Sequence[Dict[str, Any]],
    selected_vars: Sequence[str],
) -> Optional[Dict[str, float]]:
    if not rows:
        return None
    try:
        X = np.array([[float(row[v]) for v in selected_vars] for row in rows], dtype=float)
        y = np.array([math.log(float(row["sale_price"])) for row in rows], dtype=float)
        coeffs, _, _ = _fit_ridge_log_model(X, y, alpha=RIDGE_ALPHA)
        return {name: float(coeffs[idx]) for idx, name in enumerate(selected_vars)}
    except Exception:
        return None


def _subject_summary(subject: cma.PropertySnapshot, as_of_date: dt.date) -> Dict[str, Any]:
    metadata = _metadata_dict(subject)
    return {
        "parcel_number": subject.parcel_number,
        "address": subject.address,
        "land_use_code": _norm_text(metadata.get("land_use_code")),
        "property_type": subject.property_type,
        "valuation_date": as_of_date.isoformat(),
        "living_area": _safe_float(subject.living_area),
        "effective_year_built": subject.effective_year_built,
        "year_built": subject.year_built,
        "acres": _safe_float(subject.acres or subject.lot_acres),
    }


def _serialize_market_context(context: MarketContext) -> Dict[str, Any]:
    return {
        "subject_land_use_code": context.subject_land_use_code,
        "subject_property_type": context.subject_property_type,
        "subject_neighborhood_code": context.subject_neighborhood_code,
        "subject_city_district": context.subject_city_district,
        "subject_market_group": context.subject_market_group,
        "comp_neighborhood_codes": context.comp_neighborhood_codes,
        "comp_city_districts": context.comp_city_districts,
        "comp_market_groups": context.comp_market_groups,
    }


def _resolve_valuation_date(subject: cma.PropertySnapshot, override: Optional[dt.date]) -> dt.date:
    if isinstance(override, dt.datetime):
        return override.date()
    if isinstance(override, dt.date):
        return override
    metadata = _metadata_dict(subject)
    for key in ("valuation_date", "assessment_date"):
        candidate = metadata.get(key)
        if isinstance(candidate, dt.datetime):
            return candidate.date()
        if isinstance(candidate, dt.date):
            return candidate
    today = dt.date.today()
    # Align default valuation date to Jan 1 assessment standard when explicit date is absent.
    return dt.date(today.year, 1, 1)


def _normalize_months(months: Optional[int]) -> int:
    try:
        parsed = int(months) if months is not None else DEFAULT_MONTHS_LOOKBACK
    except Exception:
        parsed = DEFAULT_MONTHS_LOOKBACK
    return max(1, min(MAX_MONTHS_LOOKBACK, parsed))


def _normalize_sample_target(target: Optional[int]) -> int:
    try:
        parsed = int(target) if target is not None else DEFAULT_MIN_SAMPLE_TARGET
    except Exception:
        parsed = DEFAULT_MIN_SAMPLE_TARGET
    return max(10, min(200, parsed))


def _metadata_dict(snapshot: cma.PropertySnapshot) -> Dict[str, Any]:
    metadata = getattr(snapshot, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _norm_text(value: Any) -> str:
    if value in (None, "", "null"):
        return ""
    return str(value).strip().upper()


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        try:
            if value in (None, "", "null"):
                continue
            parsed = int(float(value))
            if parsed > 0:
                return parsed
        except Exception:
            continue
    return None


def _format_abs(value: Optional[float]) -> str:
    if value is None:
        return "0"
    return f"{abs(value):,.0f}"


def _round_or_none(value: Optional[float], decimals: int) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), decimals)
    except Exception:
        return None


def _r2_score(y_true: np.ndarray, y_pred: np.ndarray) -> Optional[float]:
    if len(y_true) < 2:
        return None
    sse = float(np.sum((y_true - y_pred) ** 2))
    sst = float(np.sum((y_true - float(np.mean(y_true))) ** 2))
    if sst <= 0:
        return None
    return 1.0 - (sse / sst)


def _mean_abs_pct_error(actual: np.ndarray, pred: np.ndarray) -> Optional[float]:
    if len(actual) == 0:
        return None
    mask = actual > 0
    if not np.any(mask):
        return None
    values = np.abs((pred[mask] - actual[mask]) / actual[mask])
    return float(np.mean(values))


def _median_abs_pct_error(actual: np.ndarray, pred: np.ndarray) -> Optional[float]:
    if len(actual) == 0:
        return None
    mask = actual > 0
    if not np.any(mask):
        return None
    values = np.abs((pred[mask] - actual[mask]) / actual[mask])
    return float(np.median(values))


def _compute_prb(log_prices: Sequence[float], ratios: Sequence[float]) -> Optional[float]:
    if len(log_prices) != len(ratios) or len(log_prices) < 3:
        return None
    x_mean = statistics.fmean(log_prices)
    y_mean = statistics.fmean(ratios)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(log_prices, ratios))
    denominator = sum((x - x_mean) ** 2 for x in log_prices)
    if denominator <= 0:
        return None
    return numerator / denominator


def _mean_confidence_interval(values: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    n = len(values)
    if n < 2:
        return None, None
    stdev = statistics.stdev(values)
    margin = 1.96 * (stdev / math.sqrt(n))
    mean = statistics.fmean(values)
    return mean - margin, mean + margin


def _build_market_area(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    parcel_numbers = sorted(
        {
            _norm_text(row.get("parcel_number"))
            for row in rows
            if _norm_text(row.get("parcel_number"))
        }
    )
    if not parcel_numbers:
        return {
            "point_count": 0,
            "sample_points": [],
            "footprint_geojson": None,
            "bounds": None,
        }

    geometry_rows = list(
        ParcelGeometry.objects.filter(
            parcel__parcel_number__in=parcel_numbers,
        ).values(
            "parcel__parcel_number",
            "latitude",
            "longitude",
            "centroid_geog",
            "centroid_2926",
            "geom",
            "geom_2926",
        )
    )
    points: List[Tuple[float, float]] = []
    sample_points: List[Dict[str, Any]] = []
    for row in geometry_rows:
        lat = _safe_float(row.get("latitude"))
        lon = _safe_float(row.get("longitude"))
        if lat is None or lon is None:
            centroid = row.get("centroid_geog")
            if centroid is not None:
                lat = _safe_float(getattr(centroid, "y", None))
                lon = _safe_float(getattr(centroid, "x", None))
        if lat is None or lon is None:
            centroid_2926 = row.get("centroid_2926")
            if centroid_2926 is not None:
                try:
                    centroid_copy = GEOSGeometry(
                        centroid_2926.wkb,
                        srid=getattr(centroid_2926, "srid", None),
                    )
                    if getattr(centroid_copy, "srid", None) and centroid_copy.srid != 4326:
                        centroid_copy.transform(4326)
                    lat = _safe_float(getattr(centroid_copy, "y", None))
                    lon = _safe_float(getattr(centroid_copy, "x", None))
                except Exception:
                    pass
        if lat is None or lon is None:
            geom = row.get("geom")
            if geom is not None:
                try:
                    geom_copy = GEOSGeometry(geom.wkb, srid=getattr(geom, "srid", None))
                    if getattr(geom_copy, "srid", None) and geom_copy.srid != 4326:
                        geom_copy.transform(4326)
                    centroid = geom_copy.centroid
                    lat = _safe_float(getattr(centroid, "y", None))
                    lon = _safe_float(getattr(centroid, "x", None))
                except Exception:
                    pass
        if lat is None or lon is None:
            geom_2926 = row.get("geom_2926")
            if geom_2926 is not None:
                try:
                    geom_copy = GEOSGeometry(
                        geom_2926.wkb,
                        srid=getattr(geom_2926, "srid", None),
                    )
                    if getattr(geom_copy, "srid", None) and geom_copy.srid != 4326:
                        geom_copy.transform(4326)
                    centroid = geom_copy.centroid
                    lat = _safe_float(getattr(centroid, "y", None))
                    lon = _safe_float(getattr(centroid, "x", None))
                except Exception:
                    pass
        if lat is None or lon is None:
            continue
        points.append((lon, lat))
        if len(sample_points) < 250:
            sample_points.append(
                {
                    "parcel_number": _norm_text(row.get("parcel__parcel_number")),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                }
            )

    if not points:
        return {
            "point_count": 0,
            "sample_points": [],
            "footprint_geojson": None,
            "bounds": None,
        }

    hull = _convex_hull(points)
    footprint = None
    if len(hull) >= 3:
        polygon = [[round(lon, 6), round(lat, 6)] for lon, lat in hull]
        polygon.append(polygon[0])
        footprint = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [polygon],
            },
            "properties": {"label": "Derived market area footprint", "point_count": len(points)},
        }

    lons = [lon for lon, _ in points]
    lats = [lat for _, lat in points]
    bounds = {
        "min_lon": round(min(lons), 6),
        "max_lon": round(max(lons), 6),
        "min_lat": round(min(lats), 6),
        "max_lat": round(max(lats), 6),
    }

    return {
        "point_count": len(points),
        "sample_points": sample_points,
        "footprint_geojson": footprint,
        "bounds": bounds,
    }


def _convex_hull(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    unique_points = sorted(set(points))
    if len(unique_points) <= 1:
        return list(unique_points)

    lower: List[Tuple[float, float]] = []
    for point in unique_points:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: List[Tuple[float, float]] = []
    for point in reversed(unique_points):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def _cross(
    origin: Tuple[float, float],
    a: Tuple[float, float],
    b: Tuple[float, float],
) -> float:
    return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])


def _empty_iaao_metrics() -> Dict[str, Any]:
    return {
        "sample_size": 0,
        "median_ratio": None,
        "mean_ratio": None,
        "weighted_mean_ratio": None,
        "cod": None,
        "prd": None,
        "prb": None,
        "mean_ratio_ci_95_lower": None,
        "mean_ratio_ci_95_upper": None,
    }


def _empty_iaao_compliance() -> Dict[str, Any]:
    return {
        "level_ok": False,
        "cod_ok": False,
        "prd_ok": False,
        "sample_size_ok": False,
        "sales_chasing_suspect": False,
        "targets": {
            "level_low": IAAO_LEVEL_LOW,
            "level_high": IAAO_LEVEL_HIGH,
            "cod_low": 5.0,
            "cod_high": 15.0,
            "prd_low": IAAO_PRD_LOW,
            "prd_high": IAAO_PRD_HIGH,
            "min_sample_size": IAAO_MIN_SAMPLE_SIZE,
        },
    }


def _should_retry_with_expanded_context(reasons: Sequence[str]) -> bool:
    if not reasons:
        return False
    instability_markers = {
        "design_matrix_ill_conditioned",
        "gla_split_stability_failed",
        "garage_split_stability_failed",
        "time_split_stability_failed",
        "model_fit_too_weak",
        "prediction_error_too_high",
    }
    return any(reason in instability_markers for reason in reasons)


def _error_payload(
    *,
    subject_summary: Dict[str, Any],
    warnings: List[str],
    error_message: str,
    market_context: Optional[Dict[str, Any]] = None,
    market_area: Optional[Dict[str, Any]] = None,
    sample: Optional[SampleSelection] = None,
) -> Dict[str, Any]:
    error_warnings = list(warnings)
    error_warnings.append("Adjustment support encountered an unexpected error.")
    widening_steps = []
    if sample:
        widening_steps = _build_widening_steps(
            sample.attempts,
            final_level=sample.geography_level,
            final_months=sample.months_used,
            final_count=len(sample.rows),
        )
    trust = _build_trust_assessment(
        status="error",
        months_used=sample.months_used if sample else None,
        geography_level=sample.geography_level if sample else None,
        widening_steps=widening_steps,
        warnings=error_warnings,
        iaao_compliance=None,
        retry_used=False,
        reduced_variable_set_used=False,
    )
    return {
        "model_version": MODEL_VERSION,
        "status": "error",
        "error": error_message,
        "not_enough_sales": False,
        "suppressed": False,
        "suppression_reason": None,
        "subject": subject_summary,
        "regression_sample_size": len(sample.rows) if sample else 0,
        "months_used": sample.months_used if sample else None,
        "geography_context": (
            {"level": sample.geography_level, "strategy": sample.strategy_label}
            if sample
            else None
        ),
        "market_context": market_context,
        "market_area": market_area,
        "variables_used": [],
        "coefficient_estimates": {},
        "suggested_adjustment_hints": [],
        "model_quality": {},
        "iaao_metrics": _empty_iaao_metrics(),
        "iaao_compliance": _empty_iaao_compliance(),
        "warnings": error_warnings,
        "trust_state": trust["trust_state"],
        "trust_score": trust["trust_score"],
        "trust_reasons": trust["trust_reasons"],
        "widening_steps": widening_steps,
    }


def _build_widening_steps(
    attempts: Sequence[Dict[str, Any]],
    *,
    final_level: Optional[str],
    final_months: Optional[int],
    final_count: Optional[int],
) -> List[Dict[str, Any]]:
    if not attempts:
        return []

    steps: List[Dict[str, Any]] = []
    selected_key = (
        str(final_level or "").strip(),
        int(final_months or 0),
        int(final_count or 0),
    )
    selected_marked = False
    prev_months: Optional[int] = None
    prev_strategy: Optional[str] = None

    for idx, attempt in enumerate(attempts, start=1):
        strategy = str(attempt.get("strategy") or "").strip() or "unknown"
        months = int(attempt.get("months") or 0)
        count = int(attempt.get("count") or 0)
        is_selected = (
            not selected_marked
            and (strategy, months, count) == selected_key
        )
        if is_selected:
            selected_marked = True

        notes: List[str] = []
        if idx > 1:
            if prev_months is not None and months > prev_months:
                notes.append(f"lookback widened from {prev_months} to {months} months")
            if prev_strategy and strategy != prev_strategy:
                notes.append(
                    f"context widened from {prev_strategy.replace('_', ' ')} to {strategy.replace('_', ' ')}"
                )

        steps.append(
            {
                "step": idx,
                "strategy": strategy,
                "months": months,
                "count": count,
                "selected": is_selected,
                "is_widen_step": idx > 1,
                "notes": notes,
            }
        )
        prev_months = months
        prev_strategy = strategy

    if not selected_marked and steps:
        steps[-1]["selected"] = True
    return steps


def _build_trust_assessment(
    *,
    status: str,
    months_used: Optional[int],
    geography_level: Optional[str],
    widening_steps: Sequence[Dict[str, Any]],
    warnings: Sequence[str],
    iaao_compliance: Optional[Dict[str, Any]],
    retry_used: bool,
    reduced_variable_set_used: bool,
) -> Dict[str, Any]:
    normalized_status = str(status or "").strip().lower() or "error"
    score = 85.0
    reasons: List[str] = []

    widen_count = sum(1 for step in widening_steps if step.get("is_widen_step"))
    if widen_count > 0:
        penalty = min(30, widen_count * 7)
        score -= penalty
        reasons.append(
            f"Sample required {widen_count} fallback/widen step(s), reducing market precision."
        )

    level = str(geography_level or "").strip().lower()
    if level == "city_district":
        score -= 8
        reasons.append("Model context widened to city-district level.")
    elif level == "county_sfr":
        score -= 18
        reasons.append("Model context widened to county-wide SFR level.")

    if months_used is not None:
        try:
            months_value = int(months_used)
        except (TypeError, ValueError):
            months_value = None
        if months_value is not None:
            if months_value >= FORCED_LOW_TRUST_MONTHS:
                score = min(score, 25.0)
                reasons.append("Lookback reached 120 months; market drift risk is high.")
            elif months_value >= 84:
                score -= 22
                reasons.append("Lookback exceeded 84 months; market relevance is weaker.")
            elif months_value >= 60:
                score -= 15
                reasons.append("Lookback exceeded 60 months; recency relevance is reduced.")
            elif months_value >= 36:
                score -= 8
                reasons.append("Lookback exceeded 36 months; recency relevance is reduced.")

    if retry_used:
        score -= 10
        reasons.append("Initial fit was unstable and required expanded-context retry.")

    if reduced_variable_set_used:
        score -= 6
        reasons.append("Variable set was reduced for stability, limiting adjustment detail.")

    if iaao_compliance:
        if not iaao_compliance.get("sample_size_ok", False):
            score -= 8
            reasons.append("IAAO sample-size check did not pass.")
        if not iaao_compliance.get("level_ok", False):
            score -= 6
            reasons.append("IAAO level check is outside target.")
        if not iaao_compliance.get("prd_ok", False):
            score -= 6
            reasons.append("IAAO PRD check is outside target.")
        if not iaao_compliance.get("cod_ok", False):
            score -= 5
            reasons.append("IAAO COD check is outside target.")

    for warning in warnings:
        text = str(warning or "").lower()
        if "coefficient stability check flagged" in text:
            score -= 8
            reasons.append("Coefficient drift across split samples reduced confidence.")
        if "quality/sanity checks did not pass" in text:
            score -= 15
            reasons.append("Model quality checks did not pass.")

    if normalized_status == "not_enough_sales":
        score = min(score, 20.0)
        reasons.append("Not enough sales to support reliable adjustment guidance.")
    elif normalized_status == "suppressed":
        score = min(score, 20.0)
        reasons.append("Adjustments were suppressed by quality/sanity safeguards.")
    elif normalized_status == "error":
        score = 0.0
        reasons.append("Unexpected processing error prevented reliable analysis.")

    score = max(0.0, min(100.0, score))

    months_for_state: Optional[int] = None
    try:
        if months_used is not None:
            months_for_state = int(months_used)
    except (TypeError, ValueError):
        months_for_state = None

    if normalized_status in {"not_enough_sales", "suppressed", "error"}:
        state = "low"
    elif months_for_state is not None and months_for_state >= FORCED_LOW_TRUST_MONTHS:
        state = "low"
    elif score >= TRUST_HIGH_MIN:
        state = "high"
    elif score >= TRUST_MEDIUM_MIN:
        state = "medium"
    else:
        state = "low"

    if not reasons and normalized_status == "ready":
        reasons.append("No major fallback or stability penalties were triggered.")

    deduped = list(dict.fromkeys(reasons))
    return {
        "trust_state": state,
        "trust_score": int(round(score)),
        "trust_reasons": deduped,
    }
