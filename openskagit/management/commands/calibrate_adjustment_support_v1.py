import datetime as dt
import json
import math
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit import appeals, cma
from openskagit.models import MasterParcel
from openskagit.services.adjustment_support import MODEL_VERSION, build_adjustment_support_v1
from openskagit.services.comp_adjustment_quality import compute_adjustment_quality_metrics

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


def _metadata_dict(snapshot: Optional[cma.PropertySnapshot]) -> Dict[str, Any]:
    raw = getattr(snapshot, "metadata", None) if snapshot is not None else None
    return raw if isinstance(raw, dict) else {}


def _valuation_date_from_result(subject: cma.PropertySnapshot, result: Dict[str, Any]) -> dt.date:
    raw_date = ((result.get("subject") or {}).get("valuation_date"))
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


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    if pct <= 0:
        return data[0]
    if pct >= 100:
        return data[-1]
    idx = (len(data) - 1) * (pct / 100.0)
    low = int(math.floor(idx))
    high = int(math.ceil(idx))
    if low == high:
        return data[low]
    frac = idx - low
    return data[low] * (1.0 - frac) + data[high] * frac


def _subject_features(subject: cma.PropertySnapshot, valuation_date: dt.date) -> Dict[str, Optional[float]]:
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


def _comp_features(
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

    sale_date_value = sale_date.date() if isinstance(sale_date, dt.datetime) else sale_date
    months_since_sale = (
        max((valuation_date - sale_date_value).days / 30.4375, 0.0)
        if isinstance(sale_date_value, dt.date)
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
            "total_adjustment": None,
            "adjusted_price": None,
            "adjustments": [],
        }

    factor_map = [
        ("gla", "living_area"),
        ("effective_age", "age"),
        ("has_garage", "garage"),
        ("log_lot_acres", "lot"),
        ("months_since_sale", "time"),
    ]
    total_adjustment = 0.0
    adjustments: List[Dict[str, Any]] = []
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
        adjustments.append({"key": key, "amount": round(amount, 2), "delta": round(delta, 4)})
    return {
        "total_adjustment": round(total_adjustment, 2) if adjustments else None,
        "adjusted_price": round(sale_price + total_adjustment, 2) if adjustments else None,
        "adjustments": adjustments,
    }


def _parse_land_use_codes(raw: str) -> List[str]:
    parts = [part.strip() for part in (raw or "").split(",")]
    return sorted({part for part in parts if part})


def _bucketed_sample(
    *,
    max_parcels: int,
    seed: int,
    land_use_codes: Sequence[str],
) -> List[Dict[str, Any]]:
    rows = list(
        MasterParcel.objects.filter(
            proptype__iexact="R",
            land_use_code__in=list(land_use_codes),
        ).values("parcel_number", "city_district", "hood_code")
    )
    if not rows:
        return []

    rng = random.Random(seed)
    by_bucket: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        city = str(row.get("city_district") or "").strip() or "unknown_city"
        key = city.lower()
        by_bucket.setdefault(key, []).append(row)
    for bucket_rows in by_bucket.values():
        rng.shuffle(bucket_rows)

    ordered_buckets = sorted(by_bucket.keys(), key=lambda key: len(by_bucket[key]), reverse=True)
    selected: List[Dict[str, Any]] = []
    cursor: Dict[str, int] = {key: 0 for key in ordered_buckets}
    while len(selected) < max_parcels:
        advanced = False
        for key in ordered_buckets:
            idx = cursor[key]
            bucket_rows = by_bucket[key]
            if idx >= len(bucket_rows):
                continue
            selected.append(bucket_rows[idx])
            cursor[key] += 1
            advanced = True
            if len(selected) >= max_parcels:
                break
        if not advanced:
            break
    return selected


class Command(BaseCommand):
    help = (
        "Calibration run for hidden comp stress flags (step 2). "
        "Samples parcels, applies adjustment-support outputs, and reports flag-driven quality metrics."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--max-parcels", type=int, default=40, help="Parcel sample size (default: 40).")
        parser.add_argument("--limit", type=int, default=7, help="Comparable limit per parcel (default: 7).")
        parser.add_argument("--months-lookback", type=int, default=24, help="Initial lookback months (default: 24).")
        parser.add_argument("--min-sample-target", type=int, default=30, help="Adjustment support min sample target (default: 30).")
        parser.add_argument("--seed", type=int, default=42, help="Sampling seed (default: 42).")
        parser.add_argument("--land-use-codes", type=str, default="110,111,112", help="Comma-separated subject land use codes (default: 110,111,112).")
        parser.add_argument("--json-out", type=str, default="", help="Optional JSON output path.")

    def handle(self, *args, **options) -> None:
        max_parcels = max(1, int(options.get("max_parcels") or 40))
        limit = max(1, int(options.get("limit") or 7))
        months_lookback = int(options.get("months_lookback") or 24)
        min_sample_target = int(options.get("min_sample_target") or 30)
        seed = int(options.get("seed") or 42)
        land_use_codes = _parse_land_use_codes(options.get("land_use_codes") or "")
        if not land_use_codes:
            raise CommandError("No valid --land-use-codes provided.")

        sampled = _bucketed_sample(max_parcels=max_parcels, seed=seed, land_use_codes=land_use_codes)
        if not sampled:
            raise CommandError("No eligible parcels found for calibration.")

        status_counts: Dict[str, int] = {}
        parcel_rows: List[Dict[str, Any]] = []
        net_values: List[float] = []
        gross_values: List[float] = []
        comp_count_total = 0
        primary_count_total = 0
        support_count_total = 0
        flag_counts: Dict[str, int] = {}

        for idx, parcel_row in enumerate(sampled, start=1):
            parcel_number = str(parcel_row.get("parcel_number") or "").strip()
            city_district = str(parcel_row.get("city_district") or "").strip() or "unknown_city"
            if not parcel_number:
                continue

            try:
                subject = cma.load_subject(parcel_number)
            except Exception:
                status_counts["subject_load_failed"] = status_counts.get("subject_load_failed", 0) + 1
                continue

            try:
                comps, _ = appeals._comparable_candidates(subject, limit=limit)
            except Exception:
                status_counts["comp_build_failed"] = status_counts.get("comp_build_failed", 0) + 1
                continue

            result = build_adjustment_support_v1(
                subject,
                months_lookback=months_lookback,
                min_sample_target=min_sample_target,
                debug=False,
            )
            status = str(result.get("status") or "error")
            status_counts[status] = status_counts.get(status, 0) + 1

            parcel_summary = {
                "parcel_number": parcel_number,
                "city_district": city_district,
                "status": status,
                "comp_count": len(comps),
                "primary_count": 0,
                "support_count": 0,
                "flag_counts": {},
            }

            if status == "ready" and comps:
                valuation_date = _valuation_date_from_result(subject, result)
                subject_features = _subject_features(subject, valuation_date)
                coeffs = result.get("coefficient_estimates") or {}
                for comp in comps:
                    comp_count_total += 1
                    sale_price = _safe_float(comp.sale_price)
                    comp_features = _comp_features(comp.snapshot, comp.sale_date, valuation_date)
                    adjustment = _compute_adjustment(
                        sale_price=sale_price,
                        subject_features=subject_features,
                        comp_features=comp_features,
                        coefficients=coeffs,
                    )
                    comp_living_area = _safe_float(
                        getattr(comp.snapshot, "living_area", None)
                        or _metadata_dict(comp.snapshot).get("calculated_square_footage")
                    )
                    quality = compute_adjustment_quality_metrics(
                        sale_price=sale_price,
                        total_adjustment=adjustment.get("total_adjustment"),
                        adjustments=adjustment.get("adjustments") or [],
                        subject_living_area=subject_features.get("gla"),
                        comp_living_area=comp_living_area,
                    )
                    if quality.get("group") == "primary":
                        primary_count_total += 1
                        parcel_summary["primary_count"] += 1
                    else:
                        support_count_total += 1
                        parcel_summary["support_count"] += 1
                    net_pct = _safe_float(quality.get("net_adjustment_pct"))
                    gross_pct = _safe_float(quality.get("gross_adjustment_pct"))
                    if net_pct is not None:
                        net_values.append(abs(net_pct))
                    if gross_pct is not None:
                        gross_values.append(gross_pct)
                    for flag in (quality.get("flags") or []):
                        flag_counts[flag] = flag_counts.get(flag, 0) + 1
                        parcel_summary["flag_counts"][flag] = parcel_summary["flag_counts"].get(flag, 0) + 1

            parcel_rows.append(parcel_summary)
            if idx % 5 == 0:
                self.stdout.write(f"Processed {idx}/{len(sampled)} parcels...")

        ready_count = status_counts.get("ready", 0)
        ready_with_comps_count = sum(
            1 for row in parcel_rows if row.get("status") == "ready" and int(row.get("comp_count") or 0) > 0
        )
        ready_no_comps_count = sum(
            1 for row in parcel_rows if row.get("status") == "ready" and int(row.get("comp_count") or 0) <= 0
        )
        ready_primary_lt3_count = sum(
            1
            for row in parcel_rows
            if row.get("status") == "ready"
            and int(row.get("comp_count") or 0) > 0
            and int(row.get("primary_count") or 0) < 3
        )

        calibration_status_counts = dict(status_counts)
        calibration_status_counts["ready_with_comps"] = ready_with_comps_count
        calibration_status_counts["ready_no_comps"] = ready_no_comps_count

        district_agg: Dict[str, Dict[str, Any]] = {}
        for row in parcel_rows:
            city = str(row.get("city_district") or "").strip() or "unknown_city"
            status = str(row.get("status") or "error")
            comp_count = int(row.get("comp_count") or 0)
            primary_count = int(row.get("primary_count") or 0)
            support_count = int(row.get("support_count") or 0)
            parcel_flags = row.get("flag_counts") or {}

            district = district_agg.setdefault(
                city,
                {
                    "city_district": city,
                    "parcels_evaluated": 0,
                    "status_counts": {},
                    "ready_with_comps": 0,
                    "ready_no_comps": 0,
                    "ready_primary_lt3": 0,
                    "comp_count_total": 0,
                    "primary_count_total": 0,
                    "support_count_total": 0,
                    "flag_counts": {},
                },
            )
            district["parcels_evaluated"] += 1
            district["status_counts"][status] = district["status_counts"].get(status, 0) + 1

            if status != "ready":
                continue

            if comp_count <= 0:
                district["ready_no_comps"] += 1
                continue

            district["ready_with_comps"] += 1
            district["comp_count_total"] += comp_count
            district["primary_count_total"] += primary_count
            district["support_count_total"] += support_count
            if primary_count < 3:
                district["ready_primary_lt3"] += 1

            for flag, count in parcel_flags.items():
                try:
                    parsed_count = int(count)
                except Exception:
                    parsed_count = 0
                if parsed_count <= 0:
                    continue
                district["flag_counts"][flag] = district["flag_counts"].get(flag, 0) + parsed_count

        district_rollups: List[Dict[str, Any]] = []
        for city, district in district_agg.items():
            comp_total = int(district.get("comp_count_total") or 0)
            primary_total = int(district.get("primary_count_total") or 0)
            support_total = int(district.get("support_count_total") or 0)
            ready_with_comps = int(district.get("ready_with_comps") or 0)
            ready_primary_lt3 = int(district.get("ready_primary_lt3") or 0)
            flag_totals = district.get("flag_counts") or {}
            top_flags = sorted(flag_totals.items(), key=lambda item: item[1], reverse=True)[:3]

            district_rollups.append(
                {
                    "city_district": city,
                    "parcels_evaluated": int(district.get("parcels_evaluated") or 0),
                    "status_counts": district.get("status_counts") or {},
                    "ready_with_comps": ready_with_comps,
                    "ready_no_comps": int(district.get("ready_no_comps") or 0),
                    "ready_primary_lt3": ready_primary_lt3,
                    "comp_count_total": comp_total,
                    "primary_count_total": primary_total,
                    "support_count_total": support_total,
                    "flag_counts": flag_totals,
                    "rates": {
                        "primary_share": (primary_total / comp_total) if comp_total else None,
                        "support_share": (support_total / comp_total) if comp_total else None,
                        "ready_primary_lt3_rate": (
                            ready_primary_lt3 / ready_with_comps
                            if ready_with_comps
                            else None
                        ),
                        "high_net_rate": (
                            (flag_totals.get("high_net_adjustment_pct", 0) / comp_total)
                            if comp_total
                            else None
                        ),
                        "high_gross_rate": (
                            (flag_totals.get("high_gross_adjustment_pct", 0) / comp_total)
                            if comp_total
                            else None
                        ),
                        "large_size_gap_rate": (
                            (flag_totals.get("large_size_gap", 0) / comp_total)
                            if comp_total
                            else None
                        ),
                    },
                    "top_flags": [
                        {
                            "flag": flag,
                            "count": count,
                            "rate": (count / comp_total) if comp_total else None,
                        }
                        for flag, count in top_flags
                    ],
                }
            )
        district_rollups.sort(
            key=lambda row: (
                int(row.get("ready_with_comps") or 0),
                int(row.get("parcels_evaluated") or 0),
            ),
            reverse=True,
        )

        primary_share = (primary_count_total / comp_count_total) if comp_count_total else None
        support_share = (support_count_total / comp_count_total) if comp_count_total else None
        high_gross_rate = (flag_counts.get("high_gross_adjustment_pct", 0) / comp_count_total) if comp_count_total else None
        high_net_rate = (flag_counts.get("high_net_adjustment_pct", 0) / comp_count_total) if comp_count_total else None
        large_size_rate = (flag_counts.get("large_size_gap", 0) / comp_count_total) if comp_count_total else None

        summary = {
            "model_version": MODEL_VERSION,
            "run_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "settings": {
                "max_parcels": max_parcels,
                "limit": limit,
                "months_lookback": months_lookback,
                "min_sample_target": min_sample_target,
                "seed": seed,
                "land_use_codes": land_use_codes,
            },
            "counts": {
                "parcels_sampled": len(sampled),
                "parcels_evaluated": len(parcel_rows),
                "ready": ready_count,
                "ready_with_comps": ready_with_comps_count,
                "ready_no_comps": ready_no_comps_count,
                "ready_primary_lt3": ready_primary_lt3_count,
                "comp_count_total": comp_count_total,
                "primary_count_total": primary_count_total,
                "support_count_total": support_count_total,
            },
            "status_counts": status_counts,
            "calibration_status_counts": calibration_status_counts,
            "flag_counts": flag_counts,
            "rates": {
                "primary_share": primary_share,
                "support_share": support_share,
                "high_gross_rate": high_gross_rate,
                "high_net_rate": high_net_rate,
                "large_size_gap_rate": large_size_rate,
                "ready_with_comps_rate": (
                    ready_with_comps_count / len(parcel_rows) if parcel_rows else None
                ),
                "ready_no_comps_rate": (
                    ready_no_comps_count / len(parcel_rows) if parcel_rows else None
                ),
                "ready_primary_lt3_rate": (
                    ready_primary_lt3_count / ready_with_comps_count
                    if ready_with_comps_count
                    else None
                ),
            },
            "distribution": {
                "abs_net_p50": _percentile(net_values, 50),
                "abs_net_p75": _percentile(net_values, 75),
                "abs_net_p90": _percentile(net_values, 90),
                "gross_p50": _percentile(gross_values, 50),
                "gross_p75": _percentile(gross_values, 75),
                "gross_p90": _percentile(gross_values, 90),
            },
            "district_rollups": district_rollups,
        }

        def _fmt_rate(value: Optional[float]) -> str:
            return f"{value:.3f}" if value is not None else "—"

        def _fmt_dist(value: Optional[float]) -> str:
            return f"{value:.3f}" if value is not None else "—"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Calibration complete (step-2 flag telemetry)."))
        self.stdout.write(
            f"Parcels evaluated: {summary['counts']['parcels_evaluated']} "
            f"(ready={summary['counts']['ready']}, "
            f"ready_with_comps={summary['counts']['ready_with_comps']}, "
            f"ready_no_comps={summary['counts']['ready_no_comps']})"
        )
        self.stdout.write(
            "Readiness quality: "
            f"ready_with_comps_rate={_fmt_rate(summary['rates']['ready_with_comps_rate'])} "
            f"ready_no_comps_rate={_fmt_rate(summary['rates']['ready_no_comps_rate'])} "
            f"primary_lt3_in_ready_with_comps={summary['counts']['ready_primary_lt3']} "
            f"({_fmt_rate(summary['rates']['ready_primary_lt3_rate'])})"
        )
        self.stdout.write(
            f"Comp mix: primary={summary['counts']['primary_count_total']} "
            f"support={summary['counts']['support_count_total']} total={summary['counts']['comp_count_total']}"
        )
        self.stdout.write(
            "Rates: "
            f"primary_share={_fmt_rate(summary['rates']['primary_share'])} "
            f"high_net={_fmt_rate(summary['rates']['high_net_rate'])} "
            f"high_gross={_fmt_rate(summary['rates']['high_gross_rate'])} "
            f"large_size_gap={_fmt_rate(summary['rates']['large_size_gap_rate'])}"
            if summary["counts"]["comp_count_total"]
            else "Rates: no comps evaluated"
        )
        self.stdout.write(
            "Distribution: "
            f"|net| p50={_fmt_dist(summary['distribution']['abs_net_p50'])} "
            f"p75={_fmt_dist(summary['distribution']['abs_net_p75'])} "
            f"p90={_fmt_dist(summary['distribution']['abs_net_p90'])}; "
            f"gross p50={_fmt_dist(summary['distribution']['gross_p50'])} "
            f"p75={_fmt_dist(summary['distribution']['gross_p75'])} "
            f"p90={_fmt_dist(summary['distribution']['gross_p90'])}"
            if summary["counts"]["comp_count_total"]
            else "Distribution: no comps evaluated"
        )
        self.stdout.write("District rollups (top 8 by ready_with_comps):")
        for row in summary["district_rollups"][:8]:
            rates = row.get("rates") or {}
            self.stdout.write(
                f"  - {row['city_district']}: ready_with_comps={row['ready_with_comps']}, "
                f"ready_no_comps={row['ready_no_comps']}, "
                f"primary_share={_fmt_rate(rates.get('primary_share'))}, "
                f"primary_lt3_rate={_fmt_rate(rates.get('ready_primary_lt3_rate'))}"
            )

        json_out = (options.get("json_out") or "").strip()
        if json_out:
            out_path = Path(json_out)
            if not out_path.is_absolute():
                out_path = Path(os.getcwd()) / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"summary": summary, "parcels": parcel_rows}
            out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            self.stdout.write(f"Wrote calibration JSON: {out_path}")
