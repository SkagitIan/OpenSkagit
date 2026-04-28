from __future__ import annotations

import csv
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

DELINQUENT_TOTAL_KEY = "Delinquent Taxes, Interest, and Penalty TOTAL"


def _parse_land_use_codes(raw: str) -> list[str]:
    parts = [part.strip() for part in raw.split(",")]
    return [part for part in parts if part]


def _fmt_money(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(value: Any, places: int = 2) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{places}f}"
    except (TypeError, ValueError):
        return "n/a"


def _rows_to_dicts(columns: Iterable[str], rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    col_list = list(columns)
    return [dict(zip(col_list, row)) for row in rows]


class Command(BaseCommand):
    help = "Scan parcel tax delinquency risk and return near-foreclosure leads."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--tax-year",
            type=int,
            default=int(os.getenv("TAX_SCAN_YEAR", timezone.now().year)),
            help="Tax-year keys used in ParcelHistory.taxes.summary (default: current year).",
        )
        parser.add_argument(
            "--land-use-codes",
            type=str,
            default="",
            help="Optional comma-separated land use codes (blank means all parcels).",
        )
        parser.add_argument(
            "--min-delinquent",
            type=float,
            default=7500.0,
            help="Minimum delinquent amount to include in lead results (default: 7500).",
        )
        parser.add_argument(
            "--min-ratio",
            type=float,
            default=2.5,
            help="Minimum delinquency/current-due ratio (default: 2.5).",
        )
        parser.add_argument(
            "--min-fixer-score",
            type=int,
            default=0,
            help="Minimum fixer score to include (default: 0).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum leads returned (default: 100).",
        )
        parser.add_argument(
            "--export-csv",
            type=str,
            default="",
            help="Optional CSV output path for lead rows.",
        )

    def handle(self, *args, **options) -> None:
        tax_year: int = options["tax_year"]
        land_use_codes = _parse_land_use_codes(options["land_use_codes"])
        min_delinquent = float(options["min_delinquent"])
        min_ratio = float(options["min_ratio"])
        min_fixer_score = int(options["min_fixer_score"])
        limit = int(options["limit"])
        export_csv = (options["export_csv"] or "").strip()
        apply_land_use_filter = bool(land_use_codes)

        if limit <= 0:
            raise CommandError("--limit must be greater than 0.")
        if min_delinquent < 0:
            raise CommandError("--min-delinquent cannot be negative.")
        if min_ratio < 0:
            raise CommandError("--min-ratio cannot be negative.")
        if min_fixer_score < 0:
            raise CommandError("--min-fixer-score cannot be negative.")

        due_key = f"{tax_year} Total Due"
        paid_key = f"{tax_year} Amount Paid"

        summary_sql = """
WITH tax_flags AS (
    SELECT
        ph.parcel_number,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS delinquent_total,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS total_due,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS amount_paid
    FROM openskagit_parcelhistory ph
),
res AS (
    SELECT
        mp.parcel_number,
        COALESCE(tf.delinquent_total, 0) AS delinquent_total,
        tf.total_due,
        tf.amount_paid,
        CASE
            WHEN tf.total_due > 0 THEN tf.delinquent_total / tf.total_due
            ELSE NULL
        END AS delinquency_years_proxy
    FROM master_parcel mp
    LEFT JOIN tax_flags tf ON tf.parcel_number = mp.parcel_number
    WHERE (%s = FALSE OR mp.land_use_code = ANY(%s))
)
SELECT
    COUNT(*) AS scoped_parcels,
    COUNT(*) FILTER (WHERE delinquent_total > 0) AS delinquent_parcels,
    COUNT(*) FILTER (WHERE delinquent_total > 0 AND delinquency_years_proxy >= 1.5) AS ratio_ge_1_5,
    COUNT(*) FILTER (WHERE delinquent_total > 0 AND delinquency_years_proxy >= 2.0) AS ratio_ge_2_0,
    COUNT(*) FILTER (WHERE delinquent_total > 0 AND delinquency_years_proxy >= 2.5) AS ratio_ge_2_5,
    COUNT(*) FILTER (WHERE delinquent_total > 0 AND delinquency_years_proxy >= 3.0) AS ratio_ge_3_0,
    AVG(NULLIF(delinquent_total, 0)) FILTER (WHERE delinquent_total > 0) AS avg_delinquent_total
FROM res
        """

        leads_sql = """
WITH tax_flags AS (
    SELECT
        ph.parcel_number,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS delinquent_total,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS total_due,
        NULLIF(regexp_replace(ph.taxes->'summary'->>%s, '[^0-9\\.-]', '', 'g'), '')::numeric AS amount_paid
    FROM openskagit_parcelhistory ph
),
res AS (
    SELECT
        mp.parcel_number,
        mp.situs_address,
        po.owner_name,
        mp.land_use_code,
        mp.land_use_description,
        COALESCE(mp.final_year_built, mp.year_built) AS year_built,
        mp.condition_score,
        mp.quality_score,
        mp.assessed_value,
        mp.building_value,
        tf.delinquent_total,
        tf.total_due,
        tf.amount_paid,
        CASE
            WHEN tf.total_due > 0 THEN tf.delinquent_total / tf.total_due
            ELSE NULL
        END AS delinquency_years_proxy,
        (
            CASE WHEN COALESCE(mp.condition_score, 99) <= 2 THEN 3 ELSE 0 END
            + CASE WHEN COALESCE(mp.quality_score, 99) <= 2 THEN 2 ELSE 0 END
            + CASE WHEN COALESCE(COALESCE(mp.final_year_built, mp.year_built), 9999) <= 1975 THEN 1 ELSE 0 END
            + CASE
                WHEN COALESCE(mp.assessed_value, 0) > 0
                    AND COALESCE(mp.building_value, 0) / mp.assessed_value < 0.45
                THEN 1
                ELSE 0
              END
        ) AS fixer_score
    FROM master_parcel mp
    JOIN tax_flags tf ON tf.parcel_number = mp.parcel_number
    LEFT JOIN parcel_owner po ON po.parcel_id = mp.parcel_number
    WHERE (%s = FALSE OR mp.land_use_code = ANY(%s))
)
SELECT
    parcel_number,
    situs_address,
    owner_name,
    land_use_code,
    land_use_description,
    year_built,
    condition_score,
    quality_score,
    assessed_value,
    building_value,
    delinquent_total,
    total_due,
    amount_paid,
    delinquency_years_proxy,
    fixer_score
FROM res
WHERE delinquent_total > 0
    AND delinquent_total >= %s
    AND COALESCE(delinquency_years_proxy, 0) >= %s
    AND fixer_score >= %s
ORDER BY delinquent_total DESC, delinquency_years_proxy DESC, fixer_score DESC, parcel_number
LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(
                summary_sql,
                [DELINQUENT_TOTAL_KEY, due_key, paid_key, apply_land_use_filter, land_use_codes],
            )
            summary_cols = [col[0] for col in cursor.description]
            summary_row = _rows_to_dicts(summary_cols, cursor.fetchall())[0]

            cursor.execute(
                leads_sql,
                [
                    DELINQUENT_TOTAL_KEY,
                    due_key,
                    paid_key,
                    apply_land_use_filter,
                    land_use_codes,
                    Decimal(str(min_delinquent)),
                    min_ratio,
                    min_fixer_score,
                    limit,
                ],
            )
            lead_cols = [col[0] for col in cursor.description]
            leads = _rows_to_dicts(lead_cols, cursor.fetchall())

        self.stdout.write(self.style.SUCCESS("Tax foreclosure risk scan complete."))
        self.stdout.write(
            f"Tax year keys: total_due='{due_key}', amount_paid='{paid_key}'"
        )
        if apply_land_use_filter:
            self.stdout.write(f"Land use scope: {', '.join(land_use_codes)}")
        else:
            self.stdout.write("Land use scope: all parcels")
        self.stdout.write(
            "Summary: "
            f"scoped={summary_row['scoped_parcels']}, "
            f"delinquent={summary_row['delinquent_parcels']}, "
            f"ratio>=1.5={summary_row['ratio_ge_1_5']}, "
            f"ratio>=2.0={summary_row['ratio_ge_2_0']}, "
            f"ratio>=2.5={summary_row['ratio_ge_2_5']}, "
            f"ratio>=3.0={summary_row['ratio_ge_3_0']}, "
            f"avg_delinquent={_fmt_money(summary_row['avg_delinquent_total'])}"
        )
        self.stdout.write(
            "Lead filters: "
            f"min_delinquent={_fmt_money(min_delinquent)}, "
            f"min_ratio={_fmt_num(min_ratio)}, "
            f"min_fixer_score={min_fixer_score}, "
            f"limit={limit}"
        )

        if not leads:
            self.stdout.write(self.style.WARNING("No leads matched current filters."))
            return

        self.stdout.write(self.style.SUCCESS(f"Matched leads: {len(leads)}"))
        for idx, row in enumerate(leads, start=1):
            self.stdout.write(
                f"{idx:>3}. "
                f"{row['parcel_number']} | "
                f"delinq={_fmt_money(row['delinquent_total'])} | "
                f"ratio={_fmt_num(row['delinquency_years_proxy'])} | "
                f"fixer={row['fixer_score']} | "
                f"cond={_fmt_num(row['condition_score'], 0)} | "
                f"q={_fmt_num(row['quality_score'], 0)} | "
                f"yr={row['year_built'] or 'n/a'} | "
                f"{row['situs_address'] or 'No address'}"
            )

        if export_csv:
            output_path = Path(export_csv)
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=lead_cols)
                writer.writeheader()
                writer.writerows(leads)
            self.stdout.write(self.style.SUCCESS(f"Wrote CSV: {output_path}"))
