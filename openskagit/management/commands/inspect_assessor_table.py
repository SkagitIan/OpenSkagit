import json
import csv
from django.core.management.base import BaseCommand
from django.db import connection
from pathlib import Path

NUMERIC_FIELDS = [
    "elev",
    "elevation",
    "slope",
    "aspect",
    "dist_major_road",
    "dist_floodway",
]

TEXT_FIELDS = [
    "aspect_dir",
    "flood_zone",
    "flood_zone_subtype",
    "flood_zone_id",
]

GEOM_FIELDS = [
    "geom",
    "geom_4326",
    "geom_2926",
    "centroid_geog",
]


class Command(BaseCommand):
    help = "Inspect elevation/slope/aspect/distance columns and export results as JSON or CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            default="assessor",
            help="Table name (default: assessor)",
        )
        parser.add_argument(
            "--output",
            default="json",
            choices=["json", "csv"],
            help="Output format: json or csv (default json)",
        )
        parser.add_argument(
            "--outfile",
            default="inspection_results.json",
            help="Output file name",
        )

    def handle(self, *args, **opts):
        table = opts["table"]
        output_format = opts["output"]
        outfile = opts["outfile"]

        results = {
            "numeric": {},
            "text": {},
            "geometry": {},
        }

        self.stdout.write(self.style.MIGRATE_HEADING(f"Inspecting: {table}\n"))

        # -----------------------------
        # NUMERIC COLUMNS
        # -----------------------------
        for col in NUMERIC_FIELDS:
            stats = self._inspect_numeric(table, col)
            results["numeric"][col] = stats

        # -----------------------------
        # TEXT COLUMNS
        # -----------------------------
        for col in TEXT_FIELDS:
            stats = self._inspect_text(table, col)
            results["text"][col] = stats

        # -----------------------------
        # GEOMETRY COLUMNS
        # -----------------------------
        for col in GEOM_FIELDS:
            stats = self._inspect_geometry(table, col)
            results["geometry"][col] = stats

        # -----------------------------
        # EXPORT RESULTS
        # -----------------------------
        if output_format == "json":
            Path(outfile).write_text(json.dumps(results, indent=2))
            self.stdout.write(self.style.SUCCESS(f"\nJSON exported to {outfile}"))
        else:
            self._export_csv(outfile, results)
            self.stdout.write(self.style.SUCCESS(f"\nCSV exported to {outfile}"))

        self.stdout.write(self.style.SUCCESS("\nInspection complete."))

    # =========================================================
    # Inspect numeric fields
    # =========================================================
    def _inspect_numeric(self, table, col):
        sql = f"""
            SELECT 
                COUNT(*) AS total,
                COUNT({col}) AS non_null,
                COUNT(*) - COUNT({col}) AS null_count,
                MIN({col}) AS min_val,
                MAX({col}) AS max_val,
                AVG({col}) AS avg_val,
                STDDEV({col}) AS std_val
            FROM {table};
        """

        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()

        total, non_null, nulls, min_v, max_v, avg_v, std_v = row

        data = {
            "total_rows": total,
            "non_null": non_null,
            "nulls": nulls,
            "min": min_v,
            "max": max_v,
            "avg": avg_v,
            "stddev": std_v,
            "issues": [],
        }

        # sanity checks
        if non_null == 0:
            data["issues"].append("Column is completely empty")

        if "aspect" in col and max_v and (min_v < 0 or max_v > 360):
            data["issues"].append("Aspect out of 0–360 deg range")

        if "dist" in col and min_v and min_v < 0:
            data["issues"].append("Distance is negative — impossible")

        return data

    # =========================================================
    # Inspect text fields
    # =========================================================
    def _inspect_text(self, table, col):
        sql = f"""
            SELECT 
                COUNT(*) AS total,
                COUNT({col}) AS non_null,
                COUNT(*) - COUNT({col}) AS nulls
            FROM {table};
        """

        with connection.cursor() as cursor:
            cursor.execute(sql)
            total, non_null, nulls = cursor.fetchone()

        sample = []
        if non_null > 0:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL LIMIT 10;"
                )
                sample = [r[0] for r in cursor.fetchall()]

        return {
            "total_rows": total,
            "non_null": non_null,
            "nulls": nulls,
            "sample_values": sample,
        }

    # =========================================================
    # Inspect geometry columns (fixed ST_Extent)
    # =========================================================
    def _inspect_geometry(self, table, col):
        # check existence
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name=%s AND column_name=%s
                );
                """,
                [table, col],
            )
            exists = cursor.fetchone()[0]

        if not exists:
            return {"exists": False}

        # Geography causes ST_Extent errors → cast to geometry
        cast_col = (
            f"{col}::geometry"
            if col.endswith("_geog") or "geog" in col
            else col
        )

        sql = f"""
            SELECT 
                COUNT({col}) AS non_null,
                COUNT(*) - COUNT({col}) AS nulls,
                MIN(ST_SRID({cast_col})) AS min_srid,
                MAX(ST_SRID({cast_col})) AS max_srid,
                ST_Extent({cast_col})::text AS extent
            FROM {table}
            WHERE {col} IS NOT NULL;
        """

        with connection.cursor() as cursor:
            cursor.execute(sql)
            non_null, nulls, min_srid, max_srid, extent = cursor.fetchone()

        issues = []
        if min_srid != max_srid:
            issues.append("Inconsistent SRID values")
        if non_null == 0:
            issues.append("Geometry column empty")

        return {
            "exists": True,
            "non_null": non_null,
            "nulls": nulls,
            "srid_min": min_srid,
            "srid_max": max_srid,
            "extent": extent,
            "issues": issues,
        }

    # =========================================================
    # Write CSV
    # =========================================================
    def _export_csv(self, outfile, results):
        with open(outfile, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["category", "field", "metric", "value"])

            for category, fields in results.items():
                for field, data in fields.items():
                    for metric, value in data.items():
                        writer.writerow([category, field, metric, value])
