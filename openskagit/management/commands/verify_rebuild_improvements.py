from __future__ import annotations

import math
import random
import re
from typing import List, Optional, Sequence, Set

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from openskagit.improvements_etl.pipeline import (
    ParcelAccumulator,
    CONDITION_MAP,
    QUALITY_MAP,
    _bucket_age,
    _coerce_int,
    _norm,
    BATH_TOKEN_VALUES,
)
from openskagit.models import AssessmentRoll, Assessor, Improvements


PLUMBING_TOKEN_RE = re.compile(r"(?P<count>\d+)(?P<token>[A-Z]+)")
PLUMBING_SPLIT_RE = re.compile(r"[;,]+|\s+")

INDICATOR_FIELDS = [
    "total_outbuilding_area",
    "total_deck_area",
    "total_porch_area",
    "total_garage_area",
    "total_basement_area",
    "number_of_outbuildings",
    "number_of_fireplaces",
    "bathrooms",
]

NULL_AUDIT_FIELDS = [
    "total_outbuilding_area",
    "total_deck_area",
    "total_porch_area",
    "total_garage_area",
    "total_basement_area",
    "number_of_outbuildings",
    "number_of_fireplaces",
    "bathrooms",
    "full_bathrooms",
    "half_bathrooms",
    "quality_score",
    "condition_code",
    "condition_score",
    "total_improvement_value",
]

NATURALLY_SPARSE_FIELDS = {
    "quality_score",
    "condition_code",
    "condition_score",
    "total_improvement_value",
}


def _normalize_tokens(raw: Optional[str]) -> Set[str]:
    if not raw:
        return set()
    tokens = PLUMBING_SPLIT_RE.split(raw)
    normalized: Set[str] = set()
    for token in tokens:
        token_text = token.strip().upper()
        if not token_text:
            continue
        match = PLUMBING_TOKEN_RE.match(token_text)
        if match:
            normalized.add(match.group("token"))
            continue
        normalized.add(token_text)
    return normalized


def _compare_values(expected: Optional[object], actual: Optional[object]) -> bool:
    if expected is None or actual is None:
        return expected == actual
    if isinstance(expected, float) or isinstance(actual, float):
        return math.isclose(float(expected), float(actual), rel_tol=1e-6, abs_tol=1e-2)
    return expected == actual


class Command(BaseCommand):
    help = "Verify the results of the latest rebuild_improvements run for a given roll year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roll",
            type=int,
            default=2025,
            help="Assessment roll year to verify (default: 2025).",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=30,
            help="Number of parcels to spot-check (must be between 1 and 50, default: 30).",
        )
        parser.add_argument(
            "--coverage-threshold",
            type=float,
            default=95.0,
            help="Minimum percent of parcels expected to show updated improvement fields (default: 95).",
        )
        parser.add_argument(
            "--null-threshold",
            type=float,
            default=5.0,
            help="Null-share threshold (%) that will flag non-sparse fields (default: 5).",
        )

    def handle(self, *args, **options):
        roll_year = options["roll"]
        sample_size = options["sample_size"]
        coverage_threshold = options["coverage_threshold"]
        null_threshold = options["null_threshold"]

        sample_size = max(1, min(50, sample_size))

        roll = AssessmentRoll.objects.filter(year=roll_year).first()
        if not roll:
            raise CommandError(f"No AssessmentRoll found for year {roll_year}.")

        assessor_qs = Assessor.objects.filter(roll=roll)
        total_assessors = assessor_qs.count()
        if total_assessors == 0:
            raise CommandError(f"No assessor rows found for roll {roll_year}.")

        improvements_qs = (
            Improvements.objects.filter(roll=roll)
            .exclude(parcel_number__isnull=True)
            .exclude(parcel_number__exact="")
        )
        improvement_parcel_qs = improvements_qs.values_list("parcel_number", flat=True).distinct()
        parcels_with_assessors = assessor_qs.filter(parcel_number__in=improvement_parcel_qs).count()

        coverage_q = Q()
        for field in INDICATOR_FIELDS:
            coverage_q |= Q(**{f"{field}__isnull": False})
        updated_count = assessor_qs.filter(coverage_q).filter(
            parcel_number__in=improvement_parcel_qs
        ).count()
        coverage_pct = (updated_count / total_assessors) * 100.0
        coverage_ok = coverage_pct >= coverage_threshold

        null_audit = []
        null_failures = False
        for field in NULL_AUDIT_FIELDS:
            null_count = assessor_qs.filter(**{f"{field}__isnull": True}).count()
            null_ratio = (null_count / total_assessors) * 100.0
            flagged = null_ratio > null_threshold and field not in NATURALLY_SPARSE_FIELDS
            null_audit.append(
                {
                    "field": field,
                    "null_count": null_count,
                    "null_ratio": null_ratio,
                    "flagged": flagged,
                }
            )
            if flagged:
                null_failures = True

        range_violations: List[dict] = []

        def _record_range_violation(field: str, q: Q, message: str):
            count = assessor_qs.filter(q).count()
            if not count:
                return
            samples = list(
                assessor_qs.filter(q)
                .order_by("parcel_number")
                .values_list("parcel_number", flat=True)[:5]
            )
            range_violations.append(
                {"field": field, "count": count, "message": message, "samples": samples}
            )

        _record_range_violation(
            "living_area",
            Q(living_area__isnull=False, living_area__lte=0),
            "living_area should be positive when provided.",
        )
        _record_range_violation(
            "bathrooms",
            Q(bathrooms__isnull=False, bathrooms__lt=0),
            "bathrooms should be zero or positive.",
        )
        _record_range_violation(
            "full_bathrooms",
            Q(full_bathrooms__isnull=False, full_bathrooms__lt=0),
            "full bathrooms counts cannot be negative.",
        )
        _record_range_violation(
            "half_bathrooms",
            Q(half_bathrooms__isnull=False, half_bathrooms__lt=0),
            "half bathrooms counts cannot be negative.",
        )
        _record_range_violation(
            "bedrooms",
            Q(bedrooms__isnull=False, bedrooms__lt=0),
            "bedroom counts should be zero or positive.",
        )

        quality_values = QUALITY_MAP.values()
        if quality_values:
            q_min = min(QUALITY_MAP.values())
            q_max = max(QUALITY_MAP.values())
            _record_range_violation(
                "quality_score",
                Q(quality_score__isnull=False)
                & (Q(quality_score__lt=q_min) | Q(quality_score__gt=q_max)),
                f"quality_score should stay between {q_min} and {q_max}.",
            )

        condition_values = CONDITION_MAP.values()
        if condition_values:
            c_min = min(CONDITION_MAP.values())
            c_max = max(CONDITION_MAP.values())
            _record_range_violation(
                "condition_score",
                Q(condition_score__isnull=False)
                & (Q(condition_score__lt=c_min) | Q(condition_score__gt=c_max)),
                f"condition_score should stay between {c_min} and {c_max}.",
            )

        mapping_issues: List[str] = []

        def _format_unknown(field: str, values: Sequence[str]) -> str:
            sample = ", ".join(str(v) for v in list(values)[:10])
            return f"{field} has {len(values)} unmapped values (examples: {sample})"

        quality_codes = {
            _norm(code)
            for code in improvements_qs.values_list("improvement_detail_class_code", flat=True)
            if code
        }
        unknown_quality = [code for code in quality_codes if code and code not in QUALITY_MAP]
        if unknown_quality:
            mapping_issues.append(_format_unknown("improvement_detail_class_code", unknown_quality))

        condition_codes = {
            _norm(code)
            for code in improvements_qs.values_list("condition_code", flat=True)
            if code
        }
        unknown_conditions = [code for code in condition_codes if code and code not in CONDITION_MAP]
        if unknown_conditions:
            mapping_issues.append(_format_unknown("condition_code", unknown_conditions))

        plumbing_entries = improvements_qs.values_list("plumbing_code", flat=True).distinct()
        unknown_tokens: Set[str] = set()
        for raw_code in plumbing_entries:
            for token in _normalize_tokens(raw_code):
                if token and token not in BATH_TOKEN_VALUES:
                    unknown_tokens.add(token)
        if unknown_tokens:
            mapping_issues.append(_format_unknown("plumbing tokens", sorted(unknown_tokens)))

        improvement_parcels = list(improvement_parcel_qs)
        sample_mismatches: List[dict] = []

        sampled_parcels = []
        if improvement_parcels:
            sample_size = min(sample_size, len(improvement_parcels))
            sampled_parcels = random.sample(improvement_parcels, sample_size)
        else:
            self.stdout.write("No improvement parcels were found for this roll; skipping spot sample.")

        for parcel in sampled_parcels:
            assessor = Assessor.objects.filter(roll=roll, parcel_number=parcel).first()
            if not assessor:
                sample_mismatches.append(
                    {
                        "parcel": parcel,
                        "issue": "No assessor row found for this parcel.",
                    }
                )
                continue

            rows = list(
                improvements_qs.filter(parcel_number=parcel).values(
                    "parcel_number",
                    "plumbing_code",
                    "improvement_detail_type_code",
                    "improvement_detail_class_code",
                    "improvement_detail_value",
                    "calculated_area",
                    "total_living_area",
                    "condition_code",
                    "effective_year_built",
                    "actual_year_built",
                    "new_construction_year",
                    "fireplace",
                )
            )

            accumulator = ParcelAccumulator(parcel_number=parcel)
            for row in rows:
                accumulator.add_row(row)

            expected: dict = {}
            expected["total_outbuilding_area"] = accumulator.total_outbuilding_area
            expected["total_deck_area"] = accumulator.total_deck_area
            expected["total_porch_area"] = accumulator.total_porch_area
            expected["total_garage_area"] = accumulator.total_garage_area
            expected["total_basement_area"] = accumulator.total_basement_area
            expected["number_of_shops"] = accumulator.number_of_shops
            expected["number_of_sheds"] = accumulator.number_of_sheds
            expected["number_of_outbuildings"] = accumulator.number_of_outbuildings
            expected["number_of_fireplaces"] = accumulator.number_of_fireplaces
            expected["has_pool"] = bool(accumulator.has_pool)
            expected["has_shop"] = bool(accumulator.has_shop)
            expected["has_deck"] = bool(accumulator.has_deck)

            finished_basement_value = None
            if accumulator.has_finished_basement:
                finished_basement_value = True
            elif accumulator.saw_basement:
                finished_basement_value = False
            expected["has_finished_basement"] = finished_basement_value

            if accumulator.bath_evidence:
                total_bathrooms = (
                    accumulator.bath_full
                    + (accumulator.bath_half * 0.5)
                    + (accumulator.bath_quarter * 0.25)
                )
                expected["bathrooms"] = total_bathrooms
                expected["full_bathrooms"] = accumulator.bath_full
                expected["half_bathrooms"] = accumulator.bath_half
            else:
                expected["bathrooms"] = None
                expected["full_bathrooms"] = None
                expected["half_bathrooms"] = None

            q_score = accumulator.quality_score()
            expected["quality_score"] = q_score
            condition = accumulator.condition()
            if condition:
                code, score = condition
                expected["condition_code"] = code
                expected["condition_score"] = score
            else:
                expected["condition_code"] = None
                expected["condition_score"] = None

            if accumulator.value_seen:
                expected["total_improvement_value"] = accumulator.total_improvement_value
            else:
                expected["total_improvement_value"] = None

            final_year_raw = (
                accumulator.best_effective_year
                or accumulator.best_actual_year
                or assessor.eff_year_built
                or assessor.year_built
            )
            final_year = _coerce_int(final_year_raw)
            if final_year:
                expected["improvement_year_built"] = final_year
                age = float(max(roll_year - final_year, 0))
                expected["age"] = age
                expected["age_sq"] = age * age
                expected["age_bucket"] = _bucket_age(age)
                if accumulator.best_new_construction_year:
                    expected["renovation_age"] = float(
                        max(roll_year - accumulator.best_new_construction_year, 0)
                    )

            mismatches: List[dict] = []
            for field, expected_value in expected.items():
                actual_value = getattr(assessor, field, None)
                if not _compare_values(expected_value, actual_value):
                    mismatches.append(
                        {
                            "field": field,
                            "expected": expected_value,
                            "actual": actual_value,
                        }
                    )

            if mismatches:
                sample_mismatches.append(
                    {
                        "parcel": parcel,
                        "mismatches": mismatches,
                    }
                )

        failures = (
            not coverage_ok
            or null_failures
            or bool(range_violations)
            or bool(mapping_issues)
            or bool(sample_mismatches)
        )

        self.stdout.write(f"\n>>> verify_rebuild_improvements report for roll {roll_year}")
        self.stdout.write(
            f"- coverage: {updated_count}/{total_assessors} parcels (~{coverage_pct:.1f}%), "
            f"threshold={coverage_threshold:.1f}% → {'PASS' if coverage_ok else 'FAIL'}"
        )
        self.stdout.write(
            f"- required fields (should be non-null after improvements): "
            f"{', '.join(INDICATOR_FIELDS)}"
        )
        self.stdout.write(
            f"- optional mapped fields (nulls expected when data is missing): "
            f"{', '.join(sorted(NATURALLY_SPARSE_FIELDS))}"
        )
        self.stdout.write(f"- parcels with improvements: {len(improvement_parcels)}")
        self.stdout.write(f"- parcels with assessor matches: {parcels_with_assessors}")

        self.stdout.write("- null/missing fields:")
        for row in null_audit:
            note = "flagged" if row["flagged"] else ""
            self.stdout.write(
                f"  • {row['field']}: {row['null_count']} nulls ({row['null_ratio']:.1f}%) {note}"
            )

        if range_violations:
            self.stdout.write("- range violations:")
            for violation in range_violations:
                samples = ", ".join(violation["samples"])
                self.stdout.write(
                    f"  • {violation['field']} ({violation['count']} rows): {violation['message']} samples: {samples}"
                )
        else:
            self.stdout.write("- range violations: none")

        if mapping_issues:
            self.stdout.write("- mapping issues:")
            for issue in mapping_issues[:5]:
                self.stdout.write(f"  • {issue}")
        else:
            self.stdout.write("- mapping issues: none")

        if sample_mismatches:
            self.stdout.write(f"- sample mismatches: {len(sample_mismatches)} parcels")
            for mismatch in sample_mismatches[:5]:
                if "issue" in mismatch:
                    self.stdout.write(f"  • {mismatch['parcel']}: {mismatch['issue']}")
                    continue
                mismatch_fields = ", ".join(
                    f"{m['field']} (expected {m['expected']} / actual {m['actual']})"
                    for m in mismatch["mismatches"]
                )
                self.stdout.write(f"  • {mismatch['parcel']}: {mismatch_fields}")
        else:
            self.stdout.write("- sample mismatches: none")

        self.stdout.write(f"- final rating: {'PASS' if not failures else 'FAIL'}")

        if failures:
            raise CommandError("verify_rebuild_improvements detected issues; see report above.")
