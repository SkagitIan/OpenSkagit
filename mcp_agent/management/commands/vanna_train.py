from django.core.management.base import BaseCommand
from django.db import connection

from mcp_agent.vanna_client import get_vn


class Command(BaseCommand):
    help = "Train Vanna on Postgres schema"

    def handle(self, *args, **kwargs):
        vn = get_vn()

        # pull schema text from Postgres (concise, not your whole POSTGIS_SCHEMA.md)
        with connection.cursor() as cur:
            cur.execute("""
                select table_schema, table_name, column_name, data_type
                from information_schema.columns
                where table_schema not in ('pg_catalog','information_schema')
                order by table_schema, table_name, ordinal_position
            """)
            rows = cur.fetchall()

        # build compact DDL-ish text
        lines = []
        current = None
        for schema, table, col, typ in rows:
            key = f"{schema}.{table}"
            if key != current:
                lines.append(f"\n-- {key}")
                current = key
            lines.append(f"{col} {typ}")
        schema_doc = "\n".join(lines)

        vn.train(documentation=schema_doc)

        # add a few canonical examples (high leverage)
        vn.train(
            question="How many sales were in Sedro-Woolley in 2025?",
            sql="""
            select count(*) as sale_count
            from public.sales
            where sale_date >= date '2025-01-01'
              and sale_date <  date '2026-01-01'
              and city = 'Sedro-Woolley'
            """
        )

        self.stdout.write(self.style.SUCCESS("Vanna training complete."))
