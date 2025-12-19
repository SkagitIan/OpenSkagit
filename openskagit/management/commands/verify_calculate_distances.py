from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from openskagit.models import Assessor, AssessmentRoll

TARGET_SRID = 2926
MAX_REASONABLE_DISTANCE_METERS = 200_000
DEFAULT_SPATIAL_SAMPLE = 30
DEFAULT_NN_SAMPLE = 30
DEFAULT_DISTANCE_TOLERANCE = 10.0
COVERAGE_THRESHOLD_DEFAULT = 95.0
SPATIAL_SAMPLE_MIN = 5
SPATIAL_SAMPLE_MAX = 100
NN_SAMPLE_MIN = 10
NN_SAMPLE_MAX = 100


@dataclass(frozen=True)
class MetricSpec:
    field: str
    label: str
    source_table: str
    filter_clause: Optional[str]
    distance_expr: str
    knn_expr: str
    zero_impossible: bool
    description: str


METRIC_SPECS: List[MetricSpec] = [
    MetricSpec(
        field="dist_major_road",
        label="Major road",
        source_table="osm.planet_osm_roads",
        filter_clause="src.highway IN ('motorway','trunk','primary','secondary')",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=False,
        description="ST_Distance against high-capacity roads (motorway/trunk/primary/secondary).",
    ),
    MetricSpec(
        field="dist_minor_road",
        label="Minor road",
        source_table="osm.planet_osm_roads",
        filter_clause="src.highway IN ('residential','unclassified','service','tertiary')",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=False,
        description="ST_Distance against residential and tertiary roads.",
    ),
    MetricSpec(
        field="dist_floodway",
        label="Floodway",
        source_table="public.floodway_skagit",
        filter_clause=None,
        distance_expr="ST_Transform(src.wkb_geometry, 2926)",
        knn_expr="ST_Transform(src.wkb_geometry, 2926)",
        zero_impossible=False,
        description="Floodway geometries get transformed to EPSG:2926 before measuring distance.",
    ),
    MetricSpec(
        field="dist_city_center",
        label="City center",
        source_table="osm.planet_osm_point",
        filter_clause="src.place IN ('city','town','village','hamlet','suburb')",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=False,
        description="Place nodes tagged as city/town/village/hamlet/suburb.",
    ),
    MetricSpec(
        field="dist_school",
        label="School",
        source_table="osm.planet_osm_point",
        filter_clause="src.amenity = 'school'",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=True,
        description="Amenity points tagged as schools.",
    ),
    MetricSpec(
        field="dist_park",
        label="Park",
        source_table="osm.planet_osm_polygon",
        filter_clause="src.leisure = 'park' OR src.landuse = 'recreation_ground'",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=False,
        description="Park and recreation-ground polygons.",
    ),
    MetricSpec(
        field="dist_supermarket",
        label="Supermarket",
        source_table="osm.planet_osm_point",
        filter_clause="src.shop IN ('supermarket','grocery','convenience')",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=True,
        description="Convenience stores, groceries, and supermarkets.",
    ),
    MetricSpec(
        field="dist_hospital",
        label="Hospital",
        source_table="osm.planet_osm_point",
        filter_clause="src.amenity IN ('hospital','clinic')",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=True,
        description="Hospital or clinic amenities.",
    ),
    MetricSpec(
        field="dist_fire_station",
        label="Fire station",
        source_table="osm.planet_osm_point",
        filter_clause="src.amenity = 'fire_station'",
        distance_expr="src.geom_2926",
        knn_expr="src.geom_2926",
        zero_impossible=True,
        description="Fire station amenities.",
    ),
]


SOURCE_SPECS = [
    {
        "label": "OSM roads (planet_osm_roads)",
        "table": "osm.planet_osm_roads",
        "geom_column": "geom_2926",
        "expected_srid": TARGET_SRID,
        "allow_srid_mismatch": False,
        "note": "Road geometries are pre-projected into 2926.",
    },
    {
        "label": "OSM points (planet_osm_point)",
        "table": "osm.planet_osm_point",
        "geom_column": "geom_2926",
        "expected_srid": TARGET_SRID,
        "allow_srid_mismatch": False,
        "note": "Points powering city/school/hospital/fire/supermarket metrics.",
    },
    {
        "label": "OSM polygons (planet_osm_polygon)",
        "table": "osm.planet_osm_polygon",
        "geom_column": "geom_2926",
        "expected_srid": TARGET_SRID,
        "allow_srid_mismatch": False,
        "note": "Park/recreation-ground polygons.",
    },
    {
        "label": "Skagit floodway (public.floodway_skagit)",
        "table": "public.floodway_skagit",
        "geom_column": "wkb_geometry",
        "expected_srid": None,
        "allow_srid_mismatch": True,
        "note": "Floodways are transformed into 2926 on the fly.",
    },
]


def _recompute_distance(
    cursor,
    spec: MetricSpec,
    parcel_number: str,
    roll_id: int,
    assessor_table: str,
) -> Optional[float]:
    where_clause = f"WHERE {spec.filter_clause}" if spec.filter_clause else ""
    sql = f"""
        SELECT (
            SELECT ST_Distance(a.geom_2926, {spec.distance_expr})
            FROM {spec.source_table} src
            {where_clause}
            ORDER BY a.geom_2926 <-> {spec.knn_expr}
            LIMIT 1
        )
        FROM {assessor_table} a
        WHERE a.parcel_number = %s
          AND a.roll_id = %s
          AND a.geom_2926 IS NOT NULL;
    """
    cursor.execute(sql, [parcel_number, roll_id])
    row = cursor.fetchone()
    return row[0] if row else None


class Command(BaseCommand):
    help = "Verify calculate_distances results for coverage, ranges, and spatial consistency."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roll",
            type=int,
            default=2025,
            help="Assessment roll year to verify (default: 2025).",
        )
        parser.add_argument(
            "--coverage-threshold",
            type=float,
            default=COVERAGE_THRESHOLD_DEFAULT,
            help="Minimum percentage of parcels with non-null distance values (default: 95).",
        )
        parser.add_argument(
            "--distance-tolerance",
            type=float,
            default=DEFAULT_DISTANCE_TOLERANCE,
            help="Tolerance in meters when recomputing distances (default: 10).",
        )
        parser.add_argument(
            "--spatial-sample-size",
            type=int,
            default=DEFAULT_SPATIAL_SAMPLE,
            help="Number of parcels to sample for recomputing every metric (default: 30).",
        )
        parser.add_argument(
            "--nn-sample-size",
            type=int,
            default=DEFAULT_NN_SAMPLE,
            help="Parcels sampled per metric when validating nearest-neighbor logic (default: 30).",
        )
        parser.add_argument(
            "--max-distance",
            type=int,
            default=MAX_REASONABLE_DISTANCE_METERS,
            help="Flag distances above this meter threshold (200000 meters by default).",
        )

    def handle(self, *args, **options):
        roll_year = options["roll"]
        coverage_threshold = max(0.0, min(100.0, options["coverage_threshold"]))
        tolerance = max(0.0, options["distance_tolerance"])
        spatial_sample_size = max(
            SPATIAL_SAMPLE_MIN,
            min(SPATIAL_SAMPLE_MAX, options["spatial_sample_size"]),
        )
        nn_sample_size = max(
            NN_SAMPLE_MIN,
            min(NN_SAMPLE_MAX, options["nn_sample_size"]),
        )
        max_distance = max(0, options["max_distance"])

        roll = AssessmentRoll.objects.filter(year=roll_year).first()
        if not roll:
            raise CommandError(f"No AssessmentRoll found for year {roll_year}.")

        assessor_table = Assessor._meta.db_table
        assessor_qs = Assessor.objects.filter(roll=roll)
        total_assessors = assessor_qs.count()
        if total_assessors == 0:
            raise CommandError(f"No assessor rows found for roll {roll_year}.")

        coverage_results = []
        for spec in METRIC_SPECS:
            non_null_count = assessor_qs.filter(**{f"{spec.field}__isnull": False}).count()
            coverage_pct = (non_null_count / total_assessors) * 100.0
            coverage_results.append(
                {
                    "spec": spec,
                    "non_null": non_null_count,
                    "null_count": total_assessors - non_null_count,
                    "coverage_pct": coverage_pct,
                    "flagged": coverage_pct < coverage_threshold,
                }
            )

        range_violations = []

        def _record_range_violation(qs, field_label: str, message: str):
            count = qs.count()
            if count == 0:
                return
            samples = list(
                qs.order_by("parcel_number").values_list("parcel_number", flat=True)[:5]
            )
            range_violations.append(
                {"field": field_label, "count": count, "message": message, "samples": samples}
            )

        for spec in METRIC_SPECS:
            negative_qs = assessor_qs.filter(**{f"{spec.field}__lt": 0})
            _record_range_violation(
                negative_qs,
                spec.label,
                "Stored distances must not be negative.",
            )
            large_qs = assessor_qs.filter(**{f"{spec.field}__gt": max_distance})
            _record_range_violation(
                large_qs,
                spec.label,
                f"Distances exceeding {max_distance} meters are suspicious.",
            )
            if spec.zero_impossible:
                zero_qs = assessor_qs.filter(**{f"{spec.field}": 0})
                _record_range_violation(
                    zero_qs,
                    spec.label,
                    "Zero distance is unlikely because parcels should not share geometry with this feature.",
                )

        missing_geom_qs = assessor_qs.filter(geom_2926__isnull=True)
        missing_geom_count = missing_geom_qs.count()
        missing_geom_samples = list(
            missing_geom_qs.order_by("parcel_number").values_list("parcel_number", flat=True)[:5]
        )

        source_checks = []
        for source in SOURCE_SPECS:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {source['table']};")
                total = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT COUNT(*) FROM {source['table']} WHERE {source['geom_column']} IS NULL;"
                )
                null_count = cursor.fetchone()[0]
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM {source['table']}
                    WHERE {source['geom_column']} IS NOT NULL
                      AND NOT ST_IsValid({source['geom_column']});
                    """
                )
                invalid_count = cursor.fetchone()[0]
                cursor.execute(
                    f"""
                    SELECT DISTINCT ST_SRID({source['geom_column']})
                    FROM {source['table']}
                    WHERE {source['geom_column']} IS NOT NULL;
                    """
                )
                srids = sorted(
                    {
                        row[0]
                        for row in cursor.fetchall()
                        if row[0] is not None
                    }
                )
            source_checks.append(
                {
                    "label": source["label"],
                    "table": source["table"],
                    "total": total,
                    "null_count": null_count,
                    "invalid_count": invalid_count,
                    "srids": srids,
                    "expected_srid": source["expected_srid"],
                    "allow_srid_mismatch": source["allow_srid_mismatch"],
                    "note": source["note"],
                }
            )

        spatial_base_qs = assessor_qs.filter(geom_2926__isnull=False)
        spatial_sample_limit = min(spatial_sample_size, spatial_base_qs.count())
        spatial_sample_fields = ["parcel_number"] + [spec.field for spec in METRIC_SPECS]
        spatial_samples = (
            list(
                spatial_base_qs.order_by("?")
                .values(*spatial_sample_fields)[:spatial_sample_limit]
            )
            if spatial_sample_limit > 0
            else []
        )

        spatial_mismatches = []
        if spatial_samples:
            with connection.cursor() as cursor:
                for spec in METRIC_SPECS:
                    for row in spatial_samples:
                        stored_value = row.get(spec.field)
                        if stored_value is None:
                            continue
                        parcel_number = row["parcel_number"]
                        recomputed = _recompute_distance(
                            cursor, spec, parcel_number, roll.id, assessor_table
                        )
                        if recomputed is None:
                            continue
                        delta = abs(recomputed - stored_value)
                        if delta > tolerance:
                            spatial_mismatches.append(
                                {
                                    "field": spec.field,
                                    "label": spec.label,
                                    "parcel": parcel_number,
                                    "stored": stored_value,
                                    "recomputed": recomputed,
                                    "delta": delta,
                                }
                            )

        nn_mismatches = []
        with connection.cursor() as cursor:
            for spec in METRIC_SPECS:
                metric_qs = assessor_qs.filter(
                    geom_2926__isnull=False, **{f"{spec.field}__isnull": False}
                )
                available = metric_qs.count()
                if available == 0:
                    continue
                sample_limit = min(nn_sample_size, available)
                rows = list(
                    metric_qs.order_by("?")
                    .values("parcel_number", spec.field)[:sample_limit]
                )
                for row in rows:
                    parcel_number = row["parcel_number"]
                    stored_value = row[spec.field]
                    if stored_value is None:
                        continue
                    recomputed = _recompute_distance(
                        cursor, spec, parcel_number, roll.id, assessor_table
                    )
                    if recomputed is None:
                        continue
                    delta = abs(recomputed - stored_value)
                    if delta > tolerance:
                        nn_mismatches.append(
                            {
                                "field": spec.field,
                                "label": spec.label,
                                "parcel": parcel_number,
                                "stored": stored_value,
                                "recomputed": recomputed,
                                "delta": delta,
                            }
                        )

        outlier_reports = []
        with connection.cursor() as cursor:
            for spec in METRIC_SPECS:
                cursor.execute(
                    f"""
                    SELECT
                        percentile_disc(0.01) WITHIN GROUP (ORDER BY {spec.field}) AS p1,
                        percentile_disc(0.05) WITHIN GROUP (ORDER BY {spec.field}) AS p5,
                        percentile_disc(0.50) WITHIN GROUP (ORDER BY {spec.field}) AS p50,
                        percentile_disc(0.95) WITHIN GROUP (ORDER BY {spec.field}) AS p95,
                        percentile_disc(0.99) WITHIN GROUP (ORDER BY {spec.field}) AS p99,
                        AVG({spec.field}) AS mean,
                        stddev_pop({spec.field}) AS stddev,
                        MAX({spec.field}) AS max_val,
                        COUNT({spec.field}) AS non_null_count
                    FROM {assessor_table}
                    WHERE roll_id = %s AND {spec.field} IS NOT NULL;
                    """,
                    [roll.id],
                )
                stats = cursor.fetchone()
                if not stats:
                    continue
                (
                    p1,
                    p5,
                    p50,
                    p95,
                    p99,
                    mean_val,
                    stddev_val,
                    max_val,
                    non_null_count,
                ) = stats
                if not non_null_count:
                    continue
                stddev_val = stddev_val or 0.0
                mean_val = mean_val or 0.0
                percentile_99 = p99 or 0.0
                threshold = max(percentile_99, mean_val + stddev_val * 5)
                limit = min(max(5, math.ceil(non_null_count * 0.001)), 20)
                cursor.execute(
                    f"""
                    SELECT parcel_number, {spec.field}
                    FROM {assessor_table}
                    WHERE roll_id = %s AND {spec.field} IS NOT NULL
                    ORDER BY {spec.field} DESC
                    LIMIT %s;
                    """,
                    [roll.id, limit],
                )
                top_values = cursor.fetchall()
                outlier_reports.append(
                    {
                        "spec": spec,
                        "stats": {
                            "p1": p1,
                            "p5": p5,
                            "p50": p50,
                            "p95": p95,
                            "p99": p99,
                            "mean": mean_val,
                            "stddev": stddev_val,
                            "max": max_val,
                            "non_null_count": non_null_count,
                            "threshold": threshold,
                        },
                        "top": top_values,
                    }
                )

        failure_reasons: List[str] = []
        for coverage in coverage_results:
            if coverage["flagged"]:
                failure_reasons.append(
                    f"{coverage['spec'].label} coverage {coverage['coverage_pct']:.1f}% < {coverage_threshold:.1f}%"
                )
        if range_violations:
            failure_reasons.append("Range violations detected for distance fields.")
        if missing_geom_count:
            failure_reasons.append(
                f"{missing_geom_count} parcels are missing geom_2926 records."
            )
        for source in source_checks:
            problems = []
            if source["total"] == 0:
                problems.append("table is empty")
            if source["null_count"]:
                problems.append(f"{source['null_count']} null geometries")
            if source["invalid_count"]:
                problems.append(f"{source['invalid_count']} invalid geometries")
            if (
                source["expected_srid"] is not None
                and not source["allow_srid_mismatch"]
                and (not source["srids"] or any(srid != source["expected_srid"] for srid in source["srids"]))
            ):
                seen = ", ".join(str(s) for s in source["srids"]) or "none"
                problems.append(
                    f"SRID mismatch (expected {source['expected_srid']} saw {seen})"
                )
            if problems:
                failure_reasons.append(f"{source['label']} issues: {'; '.join(problems)}")
        if spatial_mismatches:
            failure_reasons.append(
                f"{len(spatial_mismatches)} spatial sample mismatches exceed {tolerance:.1f}m tolerance."
            )
        if nn_mismatches:
            failure_reasons.append(
                f"{len(nn_mismatches)} nearest-neighbor recomputations diverged by > {tolerance:.1f}m."
            )

        self.stdout.write(
            f"Distance verification report for roll {roll_year} (tolerance {tolerance:.1f}m, coverage threshold {coverage_threshold:.1f}%)."
        )
        self.stdout.write(f"{total_assessors} assessor parcels considered.")
        self.stdout.write("Coverage by metric:")
        for coverage in coverage_results:
            marker = "!" if coverage["flagged"] else " "
            self.stdout.write(
                f"{marker} {coverage['spec'].label}: {coverage['coverage_pct']:.1f}% coverage "
                f"({coverage['non_null']}/{total_assessors}, {coverage['null_count']} nulls)"
            )

        if range_violations:
            self.stdout.write("Range violations:")
            for violation in range_violations:
                samples = ", ".join(violation["samples"])
                self.stdout.write(
                    f"- {violation['field']}: {violation['count']} rows – {violation['message']} (samples: {samples})"
                )

        if missing_geom_count:
            samples = ", ".join(missing_geom_samples) or "none"
            self.stdout.write(
                f"Missing geometries: {missing_geom_count} parcels (sample: {samples})"
            )
        else:
            self.stdout.write("Missing geometries: 0 parcels.")

        if spatial_mismatches:
            self.stdout.write(
                f"Spatial consistency mismatches ({len(spatial_samples)} parcel sample):"
            )
            for mismatch in spatial_mismatches[:5]:
                self.stdout.write(
                    f"- {mismatch['label']} @ {mismatch['parcel']}: stored {mismatch['stored']:.2f}m vs recomputed "
                    f"{mismatch['recomputed']:.2f}m (Δ {mismatch['delta']:.2f}m)"
                )
        else:
            self.stdout.write("Spatial sample checks passed within tolerance.")

        if nn_mismatches:
            grouped = {}
            for mismatch in nn_mismatches:
                grouped.setdefault(mismatch["field"], []).append(mismatch)
            self.stdout.write("Nearest-neighbor mismatches:")
            for spec in METRIC_SPECS:
                mismatches = grouped.get(spec.field, [])
                if not mismatches:
                    continue
                self.stdout.write(
                    f"- {spec.label}: {len(mismatches)} parcels exceeded tolerance."
                )
        else:
            self.stdout.write("Nearest-neighbor recomputations align with stored distances.")

        self.stdout.write("Source geometry audit:")
        for source in source_checks:
            srid_info = ", ".join(str(srid) for srid in source["srids"]) or "none"
            self.stdout.write(
                f"- {source['label']}: {source['total']} features, "
                f"{source['null_count']} null geom, {source['invalid_count']} invalid, SRIDs: {srid_info}. "
                f"{source['note']}"
            )

        self.stdout.write("Outlier percentiles (1%,5%,50%,95%,99%) and top distance values:")
        for report in outlier_reports:
            stats = report["stats"]
            p1 = stats["p1"] or 0.0
            p5 = stats["p5"] or 0.0
            p50 = stats["p50"] or 0.0
            p95 = stats["p95"] or 0.0
            p99 = stats["p99"] or 0.0
            self.stdout.write(
                f"- {report['spec'].label}: p1={p1:.1f}, p5={p5:.1f}, p50={p50:.1f}, "
                f"p95={p95:.1f}, p99={p99:.1f}, max={stats['max'] or 0.0:.1f}, n={stats['non_null_count']}."
            )
            top_sample = ", ".join(
                f"{row[0]}({row[1]:.1f}m)" for row in report["top"][:5]
            )
            if top_sample:
                self.stdout.write(f"  Top values: {top_sample}")

        if failure_reasons:
            self.stdout.write(self.style.ERROR("Distance verification FAILED:"))
            for reason in failure_reasons:
                self.stdout.write(f"- {reason}")
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS("Distance verification PASSED."))
