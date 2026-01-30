from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection


OUTPUT_PATH = Path("/home/django/django_project/POSTGIS_SCHEMA.md")


def format_sample_value(value):
    """Render a scalar value for Markdown without blowing up the table."""
    if value is None:
        return "NULL"

    rendered = str(value).replace("|", "\\|").replace("\n", " ")
    if len(rendered) > 160:
        return f"{rendered[:157]}..."
    return rendered


def quote_ident(value):
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


class Command(BaseCommand):
    help = "Export authoritative Postgres/PostGIS schema to Markdown for LLM usage"

    def handle(self, *args, **options):
        schema = defaultdict(lambda: {
            "columns": [],
            "pks": [],
            "fks": [],
            "indexes": [],
            "geometry": [],
            "sample_data": {
                "columns": [],
                "row": None,
                "error": None,
            },
        })

        with connection.cursor() as cursor:

            # -----------------------------
            # Columns
            # -----------------------------
            cursor.execute("""
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    udt_name,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name, ordinal_position;
            """)
            for r in cursor.fetchall():
                schema[(r[0], r[1])]["columns"].append(r)

            # -----------------------------
            # Primary Keys
            # -----------------------------
            cursor.execute("""
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY';
            """)
            for r in cursor.fetchall():
                schema[(r[0], r[1])]["pks"].append(r[2])

            # -----------------------------
            # Foreign Keys
            # -----------------------------
            cursor.execute("""
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_schema,
                    ccu.table_name,
                    ccu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY';
            """)
            for r in cursor.fetchall():
                schema[(r[0], r[1])]["fks"].append(r)

            # -----------------------------
            # Geometry Columns (PostGIS)
            # -----------------------------
            cursor.execute("""
                SELECT
                    f_table_schema,
                    f_table_name,
                    f_geometry_column,
                    type,
                    srid
                FROM geometry_columns;
            """)
            for r in cursor.fetchall():
                schema[(r[0], r[1])]["geometry"].append(r)

            # -----------------------------
            # Indexes (INCLUDING spatial)
            # -----------------------------
            cursor.execute("""
                SELECT
                    schemaname,
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schemaname, tablename;
            """)
            for r in cursor.fetchall():
                schema[(r[0], r[1])]["indexes"].append(r)

            # -----------------------------
            # Sample Data Rows
            # -----------------------------
            for schema_key in list(schema.keys()):
                sample_info = {
                    "columns": [],
                    "row": None,
                    "error": None,
                }
                try:
                    sample_query = (
                        f"SELECT * FROM {quote_ident(schema_key[0])}."
                        f"{quote_ident(schema_key[1])} LIMIT 1"
                    )
                    cursor.execute(sample_query)
                    sample_info["columns"] = [
                        col[0] for col in cursor.description or []
                    ]
                    sample_info["row"] = cursor.fetchone()
                except Exception as exc:  # pragma: no cover - defensive
                    message = str(exc)
                    if len(message) > 200:
                        message = f"{message[:197]}..."
                    sample_info["error"] = message

                schema[schema_key]["sample_data"] = sample_info

        # -----------------------------
        # Write Markdown
        # -----------------------------
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_PATH, "w") as f:
            f.write("# Postgres / PostGIS Schema\n\n")
            f.write("Authoritative database schema exported directly from Postgres.\n")
            f.write("Use this file as the **single source of truth** for LLM-assisted coding.\n\n")

            for (schema_name, table_name), data in sorted(schema.items()):
                f.write(f"## `{schema_name}.{table_name}`\n\n")

                if data["pks"]:
                    f.write(f"**Primary Key:** {', '.join(data['pks'])}\n\n")

                if data["geometry"]:
                    f.write("**Geometry Columns:**\n")
                    for g in data["geometry"]:
                        f.write(f"- `{g[2]}` ({g[3]}, SRID {g[4]})\n")
                    f.write("\n")

                f.write("### Columns\n\n")
                f.write("| Column | Type | Nullable | Default |\n")
                f.write("|-------|------|----------|---------|\n")

                for c in data["columns"]:
                    f.write(
                        f"| `{c[2]}` | {c[3]} ({c[4]}) | {c[5]} | {c[6] or ''} |\n"
                    )

                if data["fks"]:
                    f.write("\n### Foreign Keys\n\n")
                    for fk in data["fks"]:
                        f.write(
                            f"- `{fk[2]}` → `{fk[3]}.{fk[4]}.{fk[5]}`\n"
                        )

                if data["indexes"]:
                    f.write("\n### Indexes\n\n")
                    for idx in data["indexes"]:
                        f.write(f"- `{idx[2]}`\n")
                        f.write(f"  ```sql\n  {idx[3]}\n  ```\n")

                sample_data = data.get("sample_data")
                if sample_data:
                    f.write("\n### Sample Row\n\n")
                    if sample_data["error"]:
                        f.write(
                            f"_Unable to load sample data: {sample_data['error']}._\n"
                        )
                    elif sample_data["row"]:
                        f.write("| Column | Value |\n")
                        f.write("|--------|-------|\n")
                        for col, val in zip(
                            sample_data["columns"], sample_data["row"]
                        ):
                            f.write(
                                f"| `{col}` | {format_sample_value(val)} |\n"
                            )
                    else:
                        f.write(
                            "_No sample data available (table is empty or unreadable)._\n"
                        )

                f.write("\n---\n\n")

        self.stdout.write(
            self.style.SUCCESS(f"Schema exported to {OUTPUT_PATH}")
        )
