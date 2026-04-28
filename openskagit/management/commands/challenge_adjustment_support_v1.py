import datetime as dt
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit import appeals, cma
from openskagit.services.adjustment_support import MODEL_VERSION, build_adjustment_support_v1

load_dotenv()


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    try:
        return int(round(parsed))
    except Exception:
        return None


def _parse_iso_date(value: Optional[str], field_name: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Invalid {field_name} value '{value}'. Use YYYY-MM-DD.") from exc


def _metadata_dict(snapshot: Optional[cma.PropertySnapshot]) -> Dict[str, Any]:
    data = getattr(snapshot, "metadata", None) if snapshot is not None else None
    return data if isinstance(data, dict) else {}


def _valuation_date_from_result(
    subject: cma.PropertySnapshot,
    result: Dict[str, Any],
) -> dt.date:
    subject_payload = result.get("subject") or {}
    raw_date = subject_payload.get("valuation_date")
    if raw_date:
        try:
            return dt.date.fromisoformat(str(raw_date))
        except (TypeError, ValueError):
            pass

    metadata = _metadata_dict(subject)
    for key in ("valuation_date", "assessment_date"):
        value = metadata.get(key)
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value

    today = dt.date.today()
    return dt.date(today.year, 1, 1)


def _subject_features(
    subject: cma.PropertySnapshot,
    valuation_date: dt.date,
) -> Dict[str, Optional[float]]:
    metadata = _metadata_dict(subject)
    gla = _safe_float(subject.living_area or metadata.get("calculated_square_footage"))

    year_built = _safe_int(subject.effective_year_built or subject.year_built)
    effective_age = (
        float(max(valuation_date.year - year_built, 0))
        if year_built is not None and year_built > 0
        else None
    )

    garage_sqft = _safe_float(subject.garage_sqft)
    if garage_sqft is None:
        garage_sqft = _safe_float(
            metadata.get("garage_sqft")
            or metadata.get("final_garage_area")
            or metadata.get("total_garage_area")
        )
    has_garage = 1.0 if garage_sqft is not None and garage_sqft > 0 else 0.0

    acres = _safe_float(subject.acres or subject.lot_acres or metadata.get("lot_acres"))
    log_lot_acres = math.log1p(acres) if acres is not None and acres >= 0 else None

    return {
        "gla": gla,
        "effective_age": effective_age,
        "has_garage": has_garage,
        "log_lot_acres": log_lot_acres,
        "months_since_sale": 0.0,
    }


def _comparable_features(
    snapshot: Optional[cma.PropertySnapshot],
    sale_date: Optional[dt.date],
    valuation_date: dt.date,
) -> Dict[str, Optional[float]]:
    metadata = _metadata_dict(snapshot)
    living_area = getattr(snapshot, "living_area", None) if snapshot else None
    gla = _safe_float(living_area or metadata.get("calculated_square_footage"))

    year_built = _safe_int(
        (getattr(snapshot, "effective_year_built", None) if snapshot else None)
        or (getattr(snapshot, "year_built", None) if snapshot else None)
        or metadata.get("effective_year_built")
        or metadata.get("year_built")
    )
    effective_age = (
        float(max(valuation_date.year - year_built, 0))
        if year_built is not None and year_built > 0
        else None
    )

    garage_sqft = _safe_float(getattr(snapshot, "garage_sqft", None) if snapshot else None)
    if garage_sqft is None:
        garage_sqft = _safe_float(
            metadata.get("garage_sqft")
            or metadata.get("final_garage_area")
            or metadata.get("total_garage_area")
        )
    has_garage = 1.0 if garage_sqft is not None and garage_sqft > 0 else 0.0

    acres = _safe_float(
        (getattr(snapshot, "acres", None) if snapshot else None)
        or (getattr(snapshot, "lot_acres", None) if snapshot else None)
        or metadata.get("lot_acres")
    )
    log_lot_acres = math.log1p(acres) if acres is not None and acres >= 0 else None

    comp_sale_date = sale_date.date() if isinstance(sale_date, dt.datetime) else sale_date
    months_since_sale = (
        max((valuation_date - comp_sale_date).days / 30.4375, 0.0)
        if isinstance(comp_sale_date, dt.date)
        else None
    )

    return {
        "gla": gla,
        "effective_age": effective_age,
        "has_garage": has_garage,
        "log_lot_acres": log_lot_acres,
        "months_since_sale": months_since_sale,
    }


def _compute_adjustment(
    *,
    sale_price: Optional[float],
    subject_features: Dict[str, Optional[float]],
    comp_features: Dict[str, Optional[float]],
    coefficients: Dict[str, Any],
) -> Dict[str, Any]:
    if sale_price is None or sale_price <= 0:
        return {
            "available": False,
            "total_adjustment": None,
            "adjusted_price": None,
            "net_adjustment_pct": None,
            "gross_adjustment_pct": None,
            "dominant_share": None,
            "dominant_factor": None,
            "components": [],
        }

    factor_map = [
        ("gla", "living_area"),
        ("effective_age", "age"),
        ("has_garage", "garage"),
        ("log_lot_acres", "lot"),
        ("months_since_sale", "time"),
    ]

    components: List[Dict[str, Any]] = []
    total_adjustment = 0.0
    gross_adjustment = 0.0
    for coeff_key, key in factor_map:
        beta = _safe_float(coefficients.get(coeff_key))
        subject_value = subject_features.get(coeff_key)
        comp_value = comp_features.get(coeff_key)
        if beta is None or subject_value is None or comp_value is None:
            continue
        delta = float(subject_value) - float(comp_value)
        amount = sale_price * (math.exp(beta * delta) - 1.0)
        if abs(amount) < 1.0:
            continue
        total_adjustment += amount
        gross_adjustment += abs(amount)
        components.append(
            {
                "key": key,
                "beta": beta,
                "delta": round(delta, 4),
                "amount": round(amount, 2),
                "abs_share_of_gross": None,
            }
        )

    components.sort(key=lambda item: abs(item["amount"]), reverse=True)
    for comp in components:
        if gross_adjustment > 0:
            comp["abs_share_of_gross"] = round(abs(float(comp["amount"])) / gross_adjustment, 4)

    dominant_share = (
        abs(float(components[0]["amount"])) / gross_adjustment
        if components and gross_adjustment > 0
        else None
    )
    dominant_factor = components[0]["key"] if components else None
    net_pct = total_adjustment / sale_price if sale_price > 0 else None
    gross_pct = gross_adjustment / sale_price if sale_price > 0 else None

    return {
        "available": bool(components),
        "total_adjustment": round(total_adjustment, 2) if components else None,
        "adjusted_price": round(sale_price + total_adjustment, 2) if components else None,
        "net_adjustment_pct": round(net_pct, 6) if net_pct is not None and components else None,
        "gross_adjustment_pct": round(gross_pct, 6) if gross_pct is not None and components else None,
        "dominant_share": round(dominant_share, 4) if dominant_share is not None else None,
        "dominant_factor": dominant_factor,
        "components": components,
    }


def _missing_field_flags(snapshot: Optional[cma.PropertySnapshot]) -> List[str]:
    metadata = _metadata_dict(snapshot)
    flags: List[str] = []
    bedrooms = _safe_float(
        (getattr(snapshot, "bedrooms", None) if snapshot else None)
        or metadata.get("bedrooms")
        or metadata.get("number_of_bedrooms")
    )
    baths = _safe_float(
        (getattr(snapshot, "bathrooms", None) if snapshot else None)
        or metadata.get("bathrooms")
        or metadata.get("total_baths")
    )
    gla = _safe_float(
        (getattr(snapshot, "living_area", None) if snapshot else None)
        or metadata.get("calculated_square_footage")
    )
    year_built = _safe_int(
        (getattr(snapshot, "effective_year_built", None) if snapshot else None)
        or (getattr(snapshot, "year_built", None) if snapshot else None)
        or metadata.get("effective_year_built")
        or metadata.get("year_built")
    )

    if bedrooms is None:
        flags.append("missing_bedrooms_source")
    if baths is None:
        flags.append("missing_bathrooms_source")
    if gla is None:
        flags.append("missing_gla_source")
    if year_built is None:
        flags.append("missing_year_built_source")
    return flags


def _summarize_comp_row(
    *,
    subject_features: Dict[str, Optional[float]],
    comp_features: Dict[str, Optional[float]],
    comp: cma.ComparableResult,
    adjustment: Dict[str, Any],
    net_threshold: float,
    gross_threshold: float,
    dominant_threshold: float,
) -> Dict[str, Any]:
    sale_price = _safe_float(comp.sale_price)
    total_adjustment = _safe_float(adjustment.get("total_adjustment"))
    components = adjustment.get("components") or []
    component_map = {item.get("key"): item for item in components}
    time_component = component_map.get("time")
    time_delta = _safe_float((time_component or {}).get("delta"))
    time_amount = _safe_float((time_component or {}).get("amount"))
    time_per_month = (
        (time_amount / time_delta)
        if time_amount is not None and time_delta is not None and abs(time_delta) > 1e-9
        else None
    )

    size_delta_pct = None
    subject_gla = _safe_float(subject_features.get("gla"))
    comp_gla = _safe_float(comp_features.get("gla"))
    if subject_gla and comp_gla and subject_gla > 0:
        size_delta_pct = (subject_gla - comp_gla) / subject_gla

    flags = _missing_field_flags(getattr(comp, "snapshot", None))
    net_pct = _safe_float(adjustment.get("net_adjustment_pct"))
    gross_pct = _safe_float(adjustment.get("gross_adjustment_pct"))
    dominant_share = _safe_float(adjustment.get("dominant_share"))
    dominant_factor = adjustment.get("dominant_factor")

    if net_pct is not None and abs(net_pct) >= net_threshold:
        flags.append("high_net_adjustment_pct")
    if gross_pct is not None and gross_pct >= gross_threshold:
        flags.append("high_gross_adjustment_pct")
    if dominant_share is not None and dominant_share >= dominant_threshold and dominant_factor:
        flags.append(f"dominant_{dominant_factor}_adjustment")
    if size_delta_pct is not None and abs(size_delta_pct) >= 0.25:
        flags.append("large_size_gap")

    return {
        "parcel_number": getattr(getattr(comp, "snapshot", None), "parcel_number", None),
        "address": getattr(getattr(comp, "snapshot", None), "address", None),
        "sale_date": comp.sale_date.isoformat() if isinstance(comp.sale_date, (dt.date, dt.datetime)) else None,
        "sale_price": sale_price,
        "distance_miles": _safe_float(comp.distance_miles),
        "total_adjustment": total_adjustment,
        "adjusted_price": _safe_float(adjustment.get("adjusted_price")),
        "net_adjustment_pct": net_pct,
        "gross_adjustment_pct": gross_pct,
        "dominant_factor": dominant_factor,
        "dominant_share": dominant_share,
        "size_delta_pct_of_subject": round(size_delta_pct, 6) if size_delta_pct is not None else None,
        "time_months_delta": time_delta,
        "time_adjustment": time_amount,
        "time_adjustment_per_month": round(time_per_month, 2) if time_per_month is not None else None,
        "components": components,
        "flags": sorted(set(flags)),
    }


def _median(values: Sequence[float]) -> Optional[float]:
    data = [float(v) for v in values if v is not None]
    if not data:
        return None
    return float(statistics.median(data))


class Command(BaseCommand):
    help = (
        "Challenge-test adjustment_support_v1 on a parcel's comp set. "
        "Flags oversized adjustments, dominant factor drift, and source-data gaps."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--parcel", type=str, required=True, help="Subject parcel number.")
        parser.add_argument(
            "--limit",
            type=int,
            default=appeals.EXTENDED_COMPARABLE_LIMIT,
            help=f"Comparable count to evaluate (default: {appeals.EXTENDED_COMPARABLE_LIMIT}).",
        )
        parser.add_argument(
            "--months-lookback",
            type=int,
            default=24,
            help="Adjustment support initial lookback months (default: 24).",
        )
        parser.add_argument(
            "--min-sample-target",
            type=int,
            default=30,
            help="Adjustment support minimum sample target (default: 30).",
        )
        parser.add_argument(
            "--net-threshold",
            type=float,
            default=0.15,
            help="Absolute net adjustment threshold as share of sale price (default: 0.15).",
        )
        parser.add_argument(
            "--gross-threshold",
            type=float,
            default=0.25,
            help="Gross adjustment threshold as share of sale price (default: 0.25).",
        )
        parser.add_argument(
            "--dominant-threshold",
            type=float,
            default=0.70,
            help="Single-factor dominance threshold of gross adjustment (default: 0.70).",
        )
        parser.add_argument(
            "--as-of-date",
            type=str,
            default="",
            help="Optional valuation date override YYYY-MM-DD.",
        )
        parser.add_argument(
            "--json-out",
            type=str,
            default="",
            help="Optional path to write machine-readable JSON output.",
        )

    def handle(self, *args, **options) -> None:
        parcel = (options.get("parcel") or "").strip()
        if not parcel:
            raise CommandError("--parcel is required.")

        limit = max(1, int(options.get("limit") or appeals.EXTENDED_COMPARABLE_LIMIT))
        months_lookback = int(options.get("months_lookback") or 24)
        min_sample_target = int(options.get("min_sample_target") or 30)
        net_threshold = float(options.get("net_threshold") or 0.15)
        gross_threshold = float(options.get("gross_threshold") or 0.25)
        dominant_threshold = float(options.get("dominant_threshold") or 0.70)
        as_of_date = _parse_iso_date(options.get("as_of_date") or "", "as-of-date")

        subject = cma.load_subject(parcel)
        comps, _ = appeals._comparable_candidates(subject, limit=limit)
        if not comps:
            raise CommandError(f"No comparable sales returned for parcel {parcel}.")

        result = build_adjustment_support_v1(
            subject,
            valuation_date=as_of_date,
            months_lookback=months_lookback,
            min_sample_target=min_sample_target,
            debug=False,
        )
        status = str(result.get("status") or "error")
        if status != "ready":
            payload = {
                "model_version": MODEL_VERSION,
                "parcel_number": parcel,
                "status": status,
                "warnings": result.get("warnings") or [],
                "suppression_reason": result.get("suppression_reason"),
                "not_enough_sales": bool(result.get("not_enough_sales")),
            }
            self.stdout.write(json.dumps(payload, indent=2))
            return

        valuation_date = _valuation_date_from_result(subject, result)
        subject_features = _subject_features(subject, valuation_date)
        coefficients = result.get("coefficient_estimates") or {}
        time_beta = _safe_float(coefficients.get("months_since_sale"))
        time_rate = (math.exp(time_beta) - 1.0) if time_beta is not None else None

        rows: List[Dict[str, Any]] = []
        for comp in comps:
            sale_price = _safe_float(comp.sale_price)
            comp_features = _comparable_features(comp.snapshot, comp.sale_date, valuation_date)
            adjustment = _compute_adjustment(
                sale_price=sale_price,
                subject_features=subject_features,
                comp_features=comp_features,
                coefficients=coefficients,
            )
            row = _summarize_comp_row(
                subject_features=subject_features,
                comp_features=comp_features,
                comp=comp,
                adjustment=adjustment,
                net_threshold=net_threshold,
                gross_threshold=gross_threshold,
                dominant_threshold=dominant_threshold,
            )

            # Formula integrity check: verify displayed time adjustment matches model equation.
            time_component = next(
                (item for item in (row.get("components") or []) if item.get("key") == "time"),
                None,
            )
            if time_component and time_beta is not None and sale_price:
                delta = _safe_float(time_component.get("delta"))
                amount = _safe_float(time_component.get("amount"))
                if delta is not None and amount is not None:
                    expected = sale_price * (math.exp(time_beta * delta) - 1.0)
                    if abs(expected - amount) > max(2.0, abs(expected) * 0.005):
                        row.setdefault("flags", []).append("time_formula_mismatch")

            row["flags"] = sorted(set(row.get("flags") or []))
            rows.append(row)

        net_values = [abs(_safe_float(row.get("net_adjustment_pct")) or 0.0) for row in rows]
        gross_values = [_safe_float(row.get("gross_adjustment_pct")) or 0.0 for row in rows]
        high_net_count = sum(1 for row in rows if "high_net_adjustment_pct" in (row.get("flags") or []))
        high_gross_count = sum(1 for row in rows if "high_gross_adjustment_pct" in (row.get("flags") or []))
        missing_bed_count = sum(1 for row in rows if "missing_bedrooms_source" in (row.get("flags") or []))

        summary = {
            "model_version": MODEL_VERSION,
            "parcel_number": parcel,
            "valuation_date": valuation_date.isoformat(),
            "comparable_count": len(rows),
            "regression_sample_size": result.get("regression_sample_size"),
            "months_used": result.get("months_used"),
            "geography_context": result.get("geography_context"),
            "time_rate_per_month_pct": round(time_rate * 100.0, 4) if time_rate is not None else None,
            "thresholds": {
                "net_adjustment_pct": net_threshold,
                "gross_adjustment_pct": gross_threshold,
                "dominant_factor_share": dominant_threshold,
            },
            "flag_counts": {
                "high_net_adjustment_pct": high_net_count,
                "high_gross_adjustment_pct": high_gross_count,
                "missing_bedrooms_source": missing_bed_count,
            },
            "distribution": {
                "median_abs_net_adjustment_pct": _median(net_values),
                "median_gross_adjustment_pct": _median(gross_values),
                "max_abs_net_adjustment_pct": max(net_values) if net_values else None,
                "max_gross_adjustment_pct": max(gross_values) if gross_values else None,
            },
            "warnings": result.get("warnings") or [],
        }

        ranked_rows = sorted(
            rows,
            key=lambda row: (
                -(_safe_float(row.get("gross_adjustment_pct")) or 0.0),
                -abs(_safe_float(row.get("net_adjustment_pct")) or 0.0),
            ),
        )

        self.stdout.write(
            f"{parcel} challenge test ({MODEL_VERSION}) | comps={len(rows)} "
            f"| sample={summary['regression_sample_size']} | months={summary['months_used']}"
        )
        self.stdout.write(
            "thresholds: "
            f"net>={net_threshold:.0%}, gross>={gross_threshold:.0%}, dominant>={dominant_threshold:.0%}"
        )
        if time_rate is not None:
            self.stdout.write(f"time trend: {time_rate * 100:.3f}% per month (normalized)")
        self.stdout.write(
            "flags: "
            f"high_net={high_net_count}, high_gross={high_gross_count}, missing_beds={missing_bed_count}"
        )
        self.stdout.write("")
        self.stdout.write("Top challenged comps (by gross adjustment share):")

        for idx, row in enumerate(ranked_rows[: min(10, len(ranked_rows))], start=1):
            parcel_number = row.get("parcel_number") or "?"
            sale_price = _safe_float(row.get("sale_price"))
            total_adj = _safe_float(row.get("total_adjustment"))
            net_pct = _safe_float(row.get("net_adjustment_pct"))
            gross_pct = _safe_float(row.get("gross_adjustment_pct"))
            dominant_factor = row.get("dominant_factor") or "-"
            flags = ",".join(row.get("flags") or []) or "-"
            sale_text = f"${sale_price:,.0f}" if sale_price is not None else "—"
            total_adj_text = f"${total_adj:,.0f}" if total_adj is not None else "—"
            net_text = f"{net_pct * 100:+.1f}%" if net_pct is not None else "—"
            gross_text = f"{gross_pct * 100:.1f}%" if gross_pct is not None else "—"
            self.stdout.write(
                f"{idx:>2}. {parcel_number} sale={sale_text} "
                f"net={net_text} gross={gross_text} "
                f"adj={total_adj_text} dom={dominant_factor} flags={flags}"
            )

        payload = {
            "summary": summary,
            "rows": rows,
            "advanced_result": {
                "status": result.get("status"),
                "warnings": result.get("warnings") or [],
                "coefficient_estimates": result.get("coefficient_estimates") or {},
                "variables_used": result.get("variables_used") or [],
            },
        }
        json_out = (options.get("json_out") or "").strip()
        if json_out:
            out_path = Path(json_out)
            if not out_path.is_absolute():
                out_path = Path(os.getcwd()) / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            self.stdout.write("")
            self.stdout.write(f"Wrote JSON: {out_path}")
