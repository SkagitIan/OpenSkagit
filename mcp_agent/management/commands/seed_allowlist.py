# management/commands/seed_overlay_allowlist.py
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import connection

MANIFEST_PATH = Path("/home/django/django_project/reference_table_manifest.json")

def tags_for(name: str) -> list[str]:
    n = name.lower()
    tags = []
    if "fema" in n or "flood" in n: tags.append("flood")
    if "zoning" in n: tags.append("zoning")
    if "shoreline" in n: tags.append("shoreline")
    if any(x in n for x in ["school","fire","sewer","water"]): tags.append("services")
    if "census" in n or "acs" in n: tags.append("demographics")
    return tags or ["misc"]

def cost_for(row_count: int | None) -> str:
    rc = row_count or 0
    if rc < 5000: return "cheap"
    if rc < 200000: return "medium"
    return "expensive"

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        data = json.loads(MANIFEST_PATH.read_text())

        rows = []
        for table_name, meta in data.items():
            if not table_name.startswith("reference_"):
                continue
            geom_col = meta.get("geometry_column")
            if not geom_col:
                continue

            layer_key = table_name.replace("reference_", "")
            rows.append((
                layer_key,
                f"public.{table_name}",
                geom_col,
                meta.get("srid"),
                json.dumps(meta.get("geometry_types") or {}),
                meta.get("row_count"),
                tags_for(table_name),
                cost_for(meta.get("row_count")),
            ))

        sql = """
        INSERT INTO public.overlay_layer_allowlist
          (layer_key, source_table, geom_column, srid, geometry_types, row_count, tags, cost_class)
        VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
        ON CONFLICT (layer_key) DO UPDATE SET
          source_table=excluded.source_table,
          geom_column=excluded.geom_column,
          srid=excluded.srid,
          geometry_types=excluded.geometry_types,
          row_count=excluded.row_count,
          tags=excluded.tags,
          cost_class=excluded.cost_class;
        """

        with connection.cursor() as cur:
            cur.executemany(sql, rows)

        self.stdout.write(self.style.SUCCESS(f"Seeded/updated {len(rows)} overlay layers"))