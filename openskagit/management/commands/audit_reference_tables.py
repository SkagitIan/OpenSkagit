from django.core.management.base import BaseCommand
from django.db import connection
from datetime import datetime
import json
import os
import re

OUTDIR = "var/audits"
SAMPLE_N = 300

# ---- helpers -------------------------------------------------

def q(sql, params=None):
    with connection.cursor() as c:
        c.execute(sql, params or [])
        return c.fetchall()

def q1(sql, params=None):
    rows = q(sql, params)
    return rows[0][0] if rows else None

def table_exists(schema, table):
    return q1("""
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema=%s AND table_name=%s
        )
    """, [schema, table])

def geom_info(schema, table, geom_col):
    return q("""
        SELECT
          COUNT(*) FILTER (WHERE NOT ST_IsValid({g})) AS invalid,
          COUNT(*) FILTER (WHERE {g} IS NULL) AS nulls,
          MAX(ST_SRID({g})) AS srid
        FROM "{s}"."{t}"
        WHERE {g} IS NOT NULL
    """.format(s=schema, t=table, g=geom_col))[0]

def has_gist_index(schema, table, column):
    return q1("""
        SELECT EXISTS (
          SELECT 1
          FROM pg_indexes
          WHERE schemaname=%s
            AND tablename=%s
            AND indexdef ILIKE %s
        )
    """, [schema, table, f"%USING gist ({column}%"])


# ---- manifest (v1, hardcoded for now) ------------------------

REFERENCE_TABLES = [
    {
        "name": "zoning_envelope",
        "schema": "public",
        "table": "reference_zoning_envelope",
        "geom": "geometry",
        "srid": 3857,
        "keys": ["jurisdiction", "zone_code"],
    },
    {
        "name": "wetlands",
        "schema": "public",
        "table": "reference_wetlands",
        "geom": "geometry",
        "srid": 2926,
    },
    {
        "name": "shoreline",
        "schema": "public",
        "table": "reference_shoreline_jurisdiction",
        "geom": "geometry",
        "srid": 2926,
    },
    {
        "name": "sfha",
        "schema": "public",
        "table": "reference_flood_zones",
        "geom": "geometry",
        "srid": 2926,
    },
    {
        "name": "floodway",
        "schema": "public",
        "table": "reference_floodways",
        "geom": "geometry",
        "srid": None,  # known problem
    },
    {
        "name": "sewer",
        "schema": "public",
        "table": "reference_sewer_districts",
        "geom": "geometry",
        "srid": 2926,
    },
    {
        "name": "water",
        "schema": "public",
        "table": "reference_public_water_systems_2926",
        "geom": "geom_2926",
        "srid": 2926,
    },
    {
        "name": "roads",
        "schema": "public",
        "table": "reference_roads",
        "geom": "geometry",
        "srid": 2926,
    },
]

DERIVED_RULES = [
    {
        "field": "public_sewer_available",
        "evidence": ["sewer_district_id", "dist_to_sewer_main_ft"],
        "severity": "FAIL",
    },
    {
        "field": "public_water_available",
        "evidence": ["public_water_system_id", "dist_to_water_main_ft"],
        "severity": "WARN",
    },
    {
        "field": "in_sfha",
        "evidence": ["pct_area_in_sfha"],
        "severity": "WARN",
    },
    {
        "field": "in_floodway",
        "evidence": ["pct_area_in_floodway"],
        "severity": "WARN",
    },
    {
        "field": "in_wetland",
        "evidence": ["pct_area_in_wetland"],
        "severity": "WARN",
    },
]

# ---- command -------------------------------------------------

class Command(BaseCommand):
    help = "Audit planning reference tables and derived parcel_planning_facts lineage."

    def handle(self, *args, **opts):
        os.makedirs(OUTDIR, exist_ok=True)
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "reference_tables": [],
            "derived_fields": [],
            "jurisdiction_coverage": [],
        }

        # ---- reference tables ---------------------------------
        for ref in REFERENCE_TABLES:
            entry = dict(ref)
            if not table_exists(ref["schema"], ref["table"]):
                entry["status"] = "MISSING"
                report["reference_tables"].append(entry)
                continue

            entry["row_count"] = q1(
                f'SELECT COUNT(*) FROM "{ref["schema"]}"."{ref["table"]}"'
            )

            invalid, nulls, srid = geom_info(
                ref["schema"], ref["table"], ref["geom"]
            )

            entry["geometry"] = {
                "invalid": invalid,
                "nulls": nulls,
                "srid": srid,
                "expected_srid": ref["srid"],
                "srid_ok": (ref["srid"] is None or srid == ref["srid"]),
                "has_gist_index": has_gist_index(
                    ref["schema"], ref["table"], ref["geom"]
                ),
            }

            # parcel interaction
            intersect_pct = q1(f"""
                SELECT 100.0 * COUNT(DISTINCT p.parcel_id) /
                       (SELECT COUNT(*) FROM public.parcel_planning_facts)
                FROM public.parcel_planning_facts p
                JOIN public.openskagit_parcelgeometry g
                  ON g.parcel_id = p.parcel_id
                JOIN "{ref["schema"]}"."{ref["table"]}" r
                  ON ST_Intersects(g.geom_2926_valid, r.{ref["geom"]})
            """)
            entry["parcel_intersect_pct"] = round(
                float(intersect_pct or 0), 2
            )
            report["reference_tables"].append(entry)

        # ---- derived field evidence checks --------------------
        for rule in DERIVED_RULES:
            field = rule["field"]
            evidence = rule["evidence"]

            bad = q(f"""
                SELECT COUNT(*)
                FROM public.parcel_planning_facts
                WHERE {field} IS NOT NULL
                  AND ({' AND '.join(f'{e} IS NULL' for e in evidence)})
            """)[0][0]

            coverage = q(f"""
                SELECT
                  COUNT(*) FILTER (WHERE {field} IS TRUE) AS true_ct,
                  COUNT(*) FILTER (WHERE {field} IS FALSE) AS false_ct,
                  COUNT(*) FILTER (WHERE {field} IS NULL) AS null_ct
                FROM public.parcel_planning_facts
            """)[0]

            report["derived_fields"].append({
                "field": field,
                "coverage": {
                    "true": coverage[0],
                    "false": coverage[1],
                    "null": coverage[2],
                },
                "evidence_violations": bad,
                "severity": rule["severity"],
            })

        # ---- jurisdiction coverage ----------------------------
        rows = q("""
            SELECT zoning_jurisdiction,
                   COUNT(*) AS parcels,
                   AVG((in_sfha IS NOT NULL)::int) AS sfha_cov,
                   AVG((in_wetland IS NOT NULL)::int) AS wetland_cov,
                   AVG((public_sewer_available IS NOT NULL)::int) AS sewer_cov
            FROM public.parcel_planning_facts
            GROUP BY zoning_jurisdiction
            ORDER BY parcels DESC
        """)

        for r in rows:
            report["jurisdiction_coverage"].append({
                "jurisdiction": r[0],
                "parcels": r[1],
                "sfha_coverage_pct": round(float(r[2] or 0) * 100, 1),
                "wetland_coverage_pct": round(float(r[3] or 0) * 100, 1),
                "sewer_coverage_pct": round(float(r[4] or 0) * 100, 1),
            })

        # ---- write output -------------------------------------
        path = os.path.join(
            OUTDIR,
            f"planning_lineage_audit_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(path, "w") as f:
            json.dump(report, f, indent=2)

        # ---- console summary ----------------------------------
        self.stdout.write("\nPlanning Lineage Audit\n----------------------")
        self.stdout.write(f"Reference tables checked: {len(report['reference_tables'])}")
        self.stdout.write(
            f"Derived fields checked: {len(report['derived_fields'])}"
        )

        fails = [
            d for d in report["derived_fields"]
            if d["severity"] == "FAIL" and d["evidence_violations"] > 0
        ]
        if fails:
            self.stdout.write("\nFAILURES:")
            for f in fails:
                self.stdout.write(
                    f"- {f['field']}: {f['evidence_violations']} rows missing evidence"
                )

        self.stdout.write(f"\nFull report written to {path}\n")
