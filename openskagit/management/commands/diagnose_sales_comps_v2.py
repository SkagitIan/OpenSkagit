import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from openskagit import appeals, cma
from openskagit.services import sales_comps

load_dotenv()


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        return None


class Command(BaseCommand):
    help = (
        "Diagnose why build_sales_comps_v2 returns few/no comparables by showing "
        "stage-by-stage candidate drop-offs (retrieval + policy)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--parcel", required=True, help="Subject parcel number (e.g., P37123).")
        parser.add_argument(
            "--limit",
            type=int,
            default=appeals.INITIAL_COMPARABLE_LIMIT,
            help=f"Target comp count (default: {appeals.INITIAL_COMPARABLE_LIMIT}).",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=sales_comps.DEFAULT_LOOKBACK_MONTHS,
            help=f"Lookback months (default: {sales_comps.DEFAULT_LOOKBACK_MONTHS}).",
        )
        parser.add_argument(
            "--base-radius-m",
            type=float,
            default=appeals.PRIMARY_RADIUS_M,
            help=f"Base radius meters (default: {appeals.PRIMARY_RADIUS_M}).",
        )
        parser.add_argument(
            "--max-radius-m",
            type=float,
            default=appeals.SECONDARY_RADIUS_M,
            help=f"Max radius meters (default: {appeals.SECONDARY_RADIUS_M}).",
        )
        parser.add_argument("--json-out", type=str, default="", help="Optional path to write full diagnostics JSON.")

    def _stage_filters(
        self,
        subject: cma.PropertySnapshot,
        *,
        radius_meters: float,
        max_sale_age_days: int,
    ) -> Dict[str, Any]:
        subject_meta = sales_comps._subject_metadata(subject)
        subject_land_use = str(subject_meta.get("land_use_code") or "").strip()
        subject_property_type = (subject.property_type or "").strip()

        qs_base = cma._base_queryset(
            subject,
            radius_meters=radius_meters,
            max_sale_age_days=max_sale_age_days,
        )
        qs_prop = qs_base
        if subject_property_type:
            qs_prop = qs_prop.filter(
                Q(proptype__iexact=subject_property_type)
                | Q(proptype__isnull=True)
                | Q(proptype__exact="")
            )
        else:
            qs_prop = qs_prop.filter(
                Q(proptype__iexact="R")
                | Q(proptype__isnull=True)
                | Q(proptype__exact="")
            )

        qs_year = qs_prop.filter(
            Q(final_year_built__isnull=False)
            | Q(year_built__isnull=False)
            | Q(eff_year_built__isnull=False)
            | Q(effective_yr_blt__isnull=False)
        )
        qs_area = qs_year.filter(
            Q(final_living_area__isnull=False)
            | Q(total_living_area__isnull=False)
            | Q(living_area__isnull=False)
        )

        qs_land_use = qs_area
        if subject_land_use:
            qs_land_use = qs_land_use.filter(
                Q(land_use_code__iexact=subject_land_use)
                | Q(land_use_code__isnull=True)
                | Q(land_use_code__exact="")
            )

        qs_distinct = qs_land_use.order_by("parcel_number").distinct("parcel_number")
        request_limit = min(200, max(self._normalized_limit * 8, 80))
        oversample_factor = 2
        total_needed = request_limit * oversample_factor
        raw_rows = list(qs_distinct[:total_needed])
        dropped_missing_address = 0
        dropped_missing_address_parcels: List[str] = []
        for row in raw_rows:
            clean_address = cma._clean_address(getattr(row, "situs_address", None))
            if clean_address is None:
                dropped_missing_address += 1
                dropped_missing_address_parcels.append(str(getattr(row, "parcel_number", "")))

        top_land_use = list(
            qs_area.values("land_use_code")
            .annotate(count=Count("parcel_number"))
            .order_by("-count")[:10]
        )

        return {
            "radius_meters": radius_meters,
            "counts": {
                "base_queryset": qs_base.count(),
                "after_property_type_filter": qs_prop.count(),
                "after_year_presence_filter": qs_year.count(),
                "after_living_area_filter": qs_area.count(),
                "after_subject_land_use_filter": qs_land_use.count(),
                "after_distinct_parcel": qs_distinct.count(),
                "raw_rows_fetched": len(raw_rows),
                "dropped_missing_address": dropped_missing_address,
                "constructible_from_raw_rows": len(raw_rows) - dropped_missing_address,
            },
            "top_land_use_nearby": [
                {
                    "land_use_code": row.get("land_use_code"),
                    "count": int(row.get("count") or 0),
                }
                for row in top_land_use
            ],
            "dropped_missing_address_parcels": dropped_missing_address_parcels[:25],
            "request_limit": request_limit,
            "oversample_factor": oversample_factor,
        }

    def _build_pre_policy_pool(
        self,
        subject: cma.PropertySnapshot,
        *,
        radius_meters: float,
        max_sale_age_days: int,
        request_limit: int,
    ) -> List[cma.ComparableResult]:
        result = cma.build_comparables(
            subject=subject,
            filters=None,
            excluded=[],
            sort_field="score",
            sort_direction="desc",
            limit=request_limit,
            radius_meters=radius_meters,
            max_sale_age_days=max_sale_age_days,
            load_improvements=False,
            oversample_factor=2,
        )
        return list(result.comparables or [])

    def _policy_diagnostics(
        self,
        subject: cma.PropertySnapshot,
        deduped_pool: List[cma.ComparableResult],
    ) -> Dict[str, Any]:
        subject_land_use = sales_comps._land_use_code(subject)
        if subject_land_use not in sales_comps.SFR_LAND_USE_CODES:
            return {
                "policy_version": "default_v2",
                "subject_is_sfr": False,
                "tier_diagnostics": [],
            }

        ranked = sales_comps._rank_comparables(deduped_pool)
        tier_diagnostics: List[Dict[str, Any]] = []
        for idx, tier in enumerate(sales_comps.SFR_V1_TIERS, start=1):
            pass_count = 0
            reason_counts: Dict[str, int] = {}
            for comp in ranked:
                passed, reason = sales_comps._evaluate_sfr_v1_tier(subject, comp, tier)
                if passed:
                    pass_count += 1
                else:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            top_reasons = sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]
            tier_diagnostics.append(
                {
                    "tier_index": idx,
                    "pass_count": pass_count,
                    "fail_count": len(ranked) - pass_count,
                    "top_fail_reasons": [
                        {"reason": reason, "count": count} for reason, count in top_reasons
                    ],
                    "rules": {
                        "gla_ratio": [tier.gla_min_ratio, tier.gla_max_ratio],
                        "max_year_delta": tier.max_year_delta,
                        "max_bath_delta": tier.max_bath_delta,
                        "max_bed_delta": tier.max_bed_delta,
                        "max_lot_bucket_delta": tier.max_lot_bucket_delta,
                        "allow_missing_bed_bath": tier.allow_missing_bed_bath,
                    },
                }
            )
        return {
            "policy_version": "sfr_v1",
            "subject_is_sfr": True,
            "tier_diagnostics": tier_diagnostics,
        }

    def handle(self, *args, **options) -> None:
        parcel_number = str(options.get("parcel") or "").strip()
        if not parcel_number:
            raise CommandError("Provide --parcel.")

        try:
            subject = cma.load_subject(parcel_number)
        except Exception as exc:
            raise CommandError(f"Unable to load subject {parcel_number}: {exc}") from exc

        self._normalized_limit = sales_comps._normalize_limit(options.get("limit"))
        normalized_months = sales_comps._normalize_months(options.get("months"))
        base_radius = sales_comps._normalize_radius(
            options.get("base_radius_m"),
            sales_comps.DEFAULT_BASE_RADIUS_M,
        )
        max_radius = sales_comps._normalize_radius(
            options.get("max_radius_m"),
            sales_comps.DEFAULT_MAX_RADIUS_M,
        )
        if max_radius < base_radius:
            max_radius = base_radius
        max_sale_age_days = sales_comps._months_to_days(normalized_months)
        request_limit = min(200, max(self._normalized_limit * 8, 80))

        base_stage = self._stage_filters(
            subject,
            radius_meters=base_radius,
            max_sale_age_days=max_sale_age_days,
        )
        base_pool = self._build_pre_policy_pool(
            subject,
            radius_meters=base_radius,
            max_sale_age_days=max_sale_age_days,
            request_limit=request_limit,
        )
        base_unique = sales_comps._unique_comparables(base_pool)
        base_selected, _ = sales_comps._apply_selection_policy(
            subject,
            base_unique,
            limit=self._normalized_limit,
        )

        max_stage: Optional[Dict[str, Any]] = None
        max_pool: List[cma.ComparableResult] = []
        if len(base_selected) < self._normalized_limit and max_radius > base_radius:
            max_stage = self._stage_filters(
                subject,
                radius_meters=max_radius,
                max_sale_age_days=max_sale_age_days,
            )
            max_pool = self._build_pre_policy_pool(
                subject,
                radius_meters=max_radius,
                max_sale_age_days=max_sale_age_days,
                request_limit=request_limit,
            )

        combined = list(base_pool)
        combined.extend(max_pool)
        deduped = sales_comps._unique_comparables(combined)
        final_selected, policy_version = sales_comps._apply_selection_policy(
            subject,
            deduped,
            limit=self._normalized_limit,
        )

        canonical = sales_comps.build_sales_comps_v2(
            subject,
            limit=self._normalized_limit,
            months=normalized_months,
            base_radius_m=base_radius,
            max_radius_m=max_radius,
        )

        policy_diag = self._policy_diagnostics(subject, deduped)

        payload: Dict[str, Any] = {
            "parcel_number": subject.parcel_number,
            "subject": {
                "parcel_number": subject.parcel_number,
                "address": subject.address,
                "property_type": subject.property_type,
                "land_use_code": sales_comps._subject_metadata(subject).get("land_use_code"),
                "city_district": sales_comps._subject_metadata(subject).get("city_district"),
                "neighborhood_code": sales_comps._subject_metadata(subject).get("neighborhood_code"),
            },
            "inputs": {
                "limit": self._normalized_limit,
                "months": normalized_months,
                "max_sale_age_days": max_sale_age_days,
                "base_radius_m": base_radius,
                "max_radius_m": max_radius,
                "request_limit": request_limit,
            },
            "retrieval": {
                "base_radius": base_stage,
                "max_radius": max_stage,
                "pool_counts": {
                    "base_pre_policy_pool": len(base_pool),
                    "max_pre_policy_pool": len(max_pool),
                    "combined_deduped_pool": len(deduped),
                },
            },
            "policy": {
                "policy_version": policy_version,
                "diagnostics": policy_diag,
                "base_selected_count": len(base_selected),
                "final_selected_count": len(final_selected),
            },
            "canonical_result": {
                "count": len(canonical.comparables),
                "radius_used_m": canonical.radius_meters_used,
                "warnings": list(canonical.warnings or []),
            },
            "sample_final_comp_parcels": [
                getattr(getattr(comp, "snapshot", None), "parcel_number", None)
                for comp in final_selected[:15]
            ],
        }

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Diagnostics for {subject.parcel_number}"))
        self.stdout.write(
            f"Canonical comps: {payload['canonical_result']['count']} "
            f"(radius_used={payload['canonical_result']['radius_used_m']}m, policy={policy_version})"
        )
        base_counts = payload["retrieval"]["base_radius"]["counts"]
        self.stdout.write(
            "Base radius drop-off: "
            f"base={base_counts['base_queryset']} -> "
            f"land_use={base_counts['after_subject_land_use_filter']} -> "
            f"raw={base_counts['raw_rows_fetched']} -> "
            f"missing_addr_drop={base_counts['dropped_missing_address']} -> "
            f"constructible={base_counts['constructible_from_raw_rows']} -> "
            f"pre_policy_pool={payload['retrieval']['pool_counts']['base_pre_policy_pool']}"
        )
        if max_stage is not None:
            max_counts = max_stage["counts"]
            self.stdout.write(
                "Max radius drop-off: "
                f"base={max_counts['base_queryset']} -> "
                f"land_use={max_counts['after_subject_land_use_filter']} -> "
                f"raw={max_counts['raw_rows_fetched']} -> "
                f"missing_addr_drop={max_counts['dropped_missing_address']} -> "
                f"constructible={max_counts['constructible_from_raw_rows']} -> "
                f"pre_policy_pool={payload['retrieval']['pool_counts']['max_pre_policy_pool']}"
            )
        self.stdout.write(
            f"Final selected count: {payload['policy']['final_selected_count']} "
            f"from deduped pool {payload['retrieval']['pool_counts']['combined_deduped_pool']}"
        )

        json_out = (options.get("json_out") or "").strip()
        if json_out:
            out_path = Path(json_out)
            if not out_path.is_absolute():
                out_path = Path(os.getcwd()) / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            self.stdout.write(f"Wrote diagnostics JSON: {out_path}")
