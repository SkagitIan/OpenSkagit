import datetime as dt
import json
import os
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit import cma
from openskagit.models import MasterParcel, Sales
from openskagit.services.adjustment_support import MODEL_VERSION, build_adjustment_support_v1

load_dotenv()


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def _parse_iso_date(value: Optional[str], field_name: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Invalid {field_name} value '{value}'. Use YYYY-MM-DD.") from exc


def _parse_land_use_codes(raw: str) -> List[str]:
    values = [part.strip() for part in (raw or "").split(",")]
    return sorted({value for value in values if value})


class Command(BaseCommand):
    help = (
        "Backtest adjustment_support_v1 by treating historical VALID SALE records as "
        "subjects and predicting each sale using only prior sales context."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--max-sales",
            type=int,
            default=120,
            help="Maximum number of subject sales to evaluate (default: 120).",
        )
        parser.add_argument(
            "--months-lookback",
            type=int,
            default=24,
            help="Initial regression lookback months (default: 24).",
        )
        parser.add_argument(
            "--min-sample-target",
            type=int,
            default=30,
            help="Minimum target sample size for adjustment_support_v1 (default: 30).",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Filter subject sales to dates >= YYYY-MM-DD.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="Filter subject sales to dates <= YYYY-MM-DD.",
        )
        parser.add_argument(
            "--parcel",
            action="append",
            default=[],
            help="Optional parcel filter. Repeat flag for multiple parcels.",
        )
        parser.add_argument(
            "--land-use-codes",
            type=str,
            default="110,111,112",
            help="Comma-separated land use codes to include (default: 110,111,112).",
        )
        parser.add_argument(
            "--json-out",
            type=str,
            default="",
            help="Optional path to write machine-readable backtest output JSON.",
        )

    def handle(self, *args, **options) -> None:
        max_sales = max(1, int(options["max_sales"]))
        months_lookback = int(options["months_lookback"])
        min_sample_target = int(options["min_sample_target"])
        parcels = [str(value).strip() for value in (options.get("parcel") or []) if str(value).strip()]
        start_date = _parse_iso_date(options.get("start_date"), "start-date")
        end_date = _parse_iso_date(options.get("end_date"), "end-date")
        if start_date and end_date and start_date > end_date:
            raise CommandError("--start-date must be <= --end-date.")

        land_use_codes = _parse_land_use_codes(options.get("land_use_codes") or "")
        if not land_use_codes:
            raise CommandError("No valid land-use codes provided.")

        self.stdout.write(
            f"Running {MODEL_VERSION} backtest with max_sales={max_sales}, "
            f"months_lookback={months_lookback}, min_sample_target={min_sample_target}, "
            f"land_use_codes={','.join(land_use_codes)}"
        )

        eligible_parcels = MasterParcel.objects.filter(
            proptype__iexact="R",
            land_use_code__in=land_use_codes,
        ).values_list("parcel_number", flat=True)

        sales_qs = Sales.objects.filter(
            sale_type__iregex=r"^\s*valid sale\s*$",
            sale_price__gt=0,
            sale_date__isnull=False,
            parcel_number__in=eligible_parcels,
        )
        if parcels:
            sales_qs = sales_qs.filter(parcel_number__in=parcels)
        if start_date:
            sales_qs = sales_qs.filter(sale_date__date__gte=start_date)
        if end_date:
            sales_qs = sales_qs.filter(sale_date__date__lte=end_date)

        subject_sales = list(
            sales_qs.order_by("-sale_date", "-id").values(
                "id",
                "parcel_number",
                "sale_price",
                "sale_date",
            )[:max_sales]
        )
        if not subject_sales:
            self.stdout.write(self.style.WARNING("No matching subject sales found."))
            return

        status_counts: Dict[str, int] = {}
        suppression_reason_counts: Dict[str, int] = {}
        coefficient_values: Dict[str, List[float]] = {}
        iaao_samples: List[float] = []
        iaao_cod: List[float] = []
        iaao_prd: List[float] = []
        iaao_median_ratio: List[float] = []

        abs_pct_errors: List[float] = []
        signed_pct_errors: List[float] = []
        ready_with_prediction = 0

        load_subject_failures = 0
        service_exceptions = 0
        rows: List[Dict[str, Any]] = []

        for index, sale in enumerate(subject_sales, start=1):
            parcel_number = str(sale.get("parcel_number") or "").strip()
            sale_date = _safe_date(sale.get("sale_date"))
            actual_price = _safe_float(sale.get("sale_price"))
            if not parcel_number or not sale_date or not actual_price or actual_price <= 0:
                continue

            try:
                subject = cma.load_subject(parcel_number)
            except Exception:
                load_subject_failures += 1
                continue

            try:
                result = build_adjustment_support_v1(
                    subject,
                    valuation_date=sale_date,
                    months_lookback=months_lookback,
                    min_sample_target=min_sample_target,
                    debug=False,
                )
            except Exception:
                service_exceptions += 1
                status_counts["error"] = status_counts.get("error", 0) + 1
                rows.append(
                    {
                        "sale_id": sale.get("id"),
                        "parcel_number": parcel_number,
                        "sale_date": sale_date.isoformat(),
                        "actual_sale_price": actual_price,
                        "status": "error",
                        "warnings": ["unexpected_exception"],
                    }
                )
                continue

            status = str(result.get("status") or "error")
            status_counts[status] = status_counts.get(status, 0) + 1

            iaao = result.get("iaao_metrics") or {}
            for key, bucket in (
                ("sample_size", iaao_samples),
                ("cod", iaao_cod),
                ("prd", iaao_prd),
                ("median_ratio", iaao_median_ratio),
            ):
                value = _safe_float(iaao.get(key))
                if value is not None:
                    bucket.append(value)

            suppression_reason = result.get("suppression_reason")
            if suppression_reason:
                parts = [part.strip() for part in str(suppression_reason).split(",")]
                for part in parts:
                    if not part:
                        continue
                    suppression_reason_counts[part] = suppression_reason_counts.get(part, 0) + 1

            predicted_price = _safe_float(
                (result.get("model_quality") or {}).get("subject_predicted_sale_price")
            )
            if status == "ready" and predicted_price and predicted_price > 0:
                ready_with_prediction += 1
                ape = abs(predicted_price - actual_price) / actual_price
                spe = (predicted_price - actual_price) / actual_price
                abs_pct_errors.append(ape)
                signed_pct_errors.append(spe)

                for variable, value in (result.get("coefficient_estimates") or {}).items():
                    parsed = _safe_float(value)
                    if parsed is None:
                        continue
                    coefficient_values.setdefault(variable, []).append(parsed)

            rows.append(
                {
                    "sale_id": sale.get("id"),
                    "parcel_number": parcel_number,
                    "sale_date": sale_date.isoformat(),
                    "actual_sale_price": actual_price,
                    "predicted_sale_price": predicted_price,
                    "status": status,
                    "not_enough_sales": bool(result.get("not_enough_sales")),
                    "suppressed": bool(result.get("suppressed")),
                    "suppression_reason": suppression_reason,
                    "regression_sample_size": result.get("regression_sample_size"),
                    "months_used": result.get("months_used"),
                    "geography_level": ((result.get("geography_context") or {}).get("level")),
                }
            )

            if index % 25 == 0:
                self.stdout.write(f"Processed {index}/{len(subject_sales)} subject sales...")

        total_processed = len(rows)
        ready_count = status_counts.get("ready", 0)
        suppressed_count = status_counts.get("suppressed", 0)
        not_enough_count = status_counts.get("not_enough_sales", 0)
        error_count = status_counts.get("error", 0)

        def _rate(count: int) -> Optional[float]:
            if total_processed == 0:
                return None
            return count / total_processed

        coefficient_stability: Dict[str, Dict[str, Any]] = {}
        for variable, values in sorted(coefficient_values.items()):
            if not values:
                continue
            mean_value = statistics.fmean(values)
            std_value = statistics.stdev(values) if len(values) >= 2 else 0.0
            pos_share = sum(1 for v in values if v > 0) / len(values)
            neg_share = sum(1 for v in values if v < 0) / len(values)
            coefficient_stability[variable] = {
                "n": len(values),
                "mean": round(mean_value, 6),
                "median": round(statistics.median(values), 6),
                "std": round(std_value, 6),
                "sign_flip": pos_share > 0 and neg_share > 0,
                "positive_share": round(pos_share, 4),
                "negative_share": round(neg_share, 4),
            }

        summary: Dict[str, Any] = {
            "model_version": MODEL_VERSION,
            "run_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "settings": {
                "max_sales": max_sales,
                "months_lookback": months_lookback,
                "min_sample_target": min_sample_target,
                "land_use_codes": land_use_codes,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "parcel_filter": parcels,
            },
            "counts": {
                "subjects_selected": len(subject_sales),
                "subjects_processed": total_processed,
                "load_subject_failures": load_subject_failures,
                "service_exceptions": service_exceptions,
                "ready": ready_count,
                "suppressed": suppressed_count,
                "not_enough_sales": not_enough_count,
                "error": error_count,
            },
            "rates": {
                "ready_rate": _rate(ready_count),
                "suppression_rate": _rate(suppressed_count),
                "not_enough_sales_rate": _rate(not_enough_count),
                "error_rate": _rate(error_count),
            },
            "prediction_accuracy": {
                "ready_with_prediction": ready_with_prediction,
                "mape": round(statistics.fmean(abs_pct_errors), 4) if abs_pct_errors else None,
                "mdape": round(statistics.median(abs_pct_errors), 4) if abs_pct_errors else None,
                "mean_signed_pct_error": (
                    round(statistics.fmean(signed_pct_errors), 4) if signed_pct_errors else None
                ),
            },
            "suppression_reasons": suppression_reason_counts,
            "coefficient_stability": coefficient_stability,
            "iaao_summary": {
                "median_sample_size": (
                    round(statistics.median(iaao_samples), 2) if iaao_samples else None
                ),
                "median_cod": round(statistics.median(iaao_cod), 3) if iaao_cod else None,
                "median_prd": round(statistics.median(iaao_prd), 4) if iaao_prd else None,
                "median_ratio": (
                    round(statistics.median(iaao_median_ratio), 4) if iaao_median_ratio else None
                ),
            },
        }

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Backtest complete: {total_processed} evaluated subjects"))
        self.stdout.write(
            "Status counts: "
            + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items()))
        )
        self.stdout.write(
            "Accuracy: "
            f"MAPE={summary['prediction_accuracy']['mape']} "
            f"MDAPE={summary['prediction_accuracy']['mdape']} "
            f"(ready_with_prediction={ready_with_prediction})"
        )
        self.stdout.write(
            "Rates: "
            f"suppressed={summary['rates']['suppression_rate']} "
            f"not_enough={summary['rates']['not_enough_sales_rate']} "
            f"error={summary['rates']['error_rate']}"
        )

        json_out = (options.get("json_out") or "").strip()
        if json_out:
            out_path = Path(json_out)
            if not out_path.is_absolute():
                out_path = Path(os.getcwd()) / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"summary": summary, "rows": rows}
            out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            self.stdout.write(f"Wrote backtest JSON: {out_path}")
