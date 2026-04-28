import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from django.db import connection
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)


def _resolve_cache_path() -> Path:
    configured = Path(
        os.environ.get(
            "MCP_AGENT_SCHEMA_CACHE",
            Path(__file__).resolve().parent.parent / "var" / "mcp_schema_index.json",
        )
    )
    parent = configured.parent
    # Prefer the configured path when we have write access to the directory (or file if it exists).
    if (parent.exists() and os.access(parent, os.W_OK)) or (
        configured.exists() and os.access(configured, os.W_OK)
    ):
        return configured

    fallback = Path(tempfile.gettempdir()) / "mcp_schema_index.json"
    if configured != fallback:
        logger.warning(
            "Schema cache path %s is not writable; falling back to %s",
            configured,
            fallback,
        )
    return fallback


SCHEMA_CACHE_PATH = _resolve_cache_path()
SCHEMA_MAX_AGE_SECONDS = int(os.environ.get("MCP_AGENT_SCHEMA_MAX_AGE_SECONDS", 24 * 3600))


@dataclass
class SchemaColumn:
    name: str
    type: str


@dataclass
class SchemaForeignKey:
    column: str
    ref: str


@dataclass
class SchemaGeometry:
    column: str
    srid: Optional[int] = None


@dataclass
class SchemaTable:
    columns: List[SchemaColumn]
    fkeys: List[SchemaForeignKey] = field(default_factory=list)
    row_est: Optional[int] = None
    geometry: List[SchemaGeometry] = field(default_factory=list)


SchemaIndex = Dict[str, SchemaTable]

_memory_cache: Optional[Dict[str, object]] = None


def _ensure_cache_dir() -> None:
    SCHEMA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _fetch_columns() -> Dict[str, List[SchemaColumn]]:
    sql = """
        select table_schema, table_name, column_name, data_type
        from information_schema.columns
        where table_schema not in ('pg_catalog','information_schema')
        order by table_schema, table_name, ordinal_position;
    """
    columns: Dict[str, List[SchemaColumn]] = {}
    with connection.cursor() as cur:
        cur.execute(sql)
        for schema, table, col, typ in cur.fetchall():
            key = f"{schema}.{table}"
            columns.setdefault(key, []).append(SchemaColumn(name=col, type=typ))
    return columns


def _fetch_row_estimates() -> Dict[str, int]:
    sql = """
        select n.nspname as schema, c.relname as table, c.reltuples::bigint as row_est
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname not in ('pg_catalog','information_schema')
          and c.relkind = 'r';
    """
    estimates: Dict[str, int] = {}
    with connection.cursor() as cur:
        cur.execute(sql)
        for schema, table, row_est in cur.fetchall():
            estimates[f"{schema}.{table}"] = int(row_est)
    return estimates


def _fetch_foreign_keys() -> Dict[str, List[SchemaForeignKey]]:
    sql = """
        select
            tc.table_schema,
            tc.table_name,
            kcu.column_name,
            ccu.table_schema as foreign_table_schema,
            ccu.table_name as foreign_table_name,
            ccu.column_name as foreign_column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
            on tc.constraint_name = kcu.constraint_name
            and tc.table_schema = kcu.table_schema
        join information_schema.constraint_column_usage ccu
            on ccu.constraint_name = tc.constraint_name
            and ccu.table_schema = tc.table_schema
        where tc.constraint_type = 'FOREIGN KEY'
          and tc.table_schema not in ('pg_catalog','information_schema');
    """
    fkeys: Dict[str, List[SchemaForeignKey]] = {}
    with connection.cursor() as cur:
        cur.execute(sql)
        for schema, table, col, ref_schema, ref_table, ref_col in cur.fetchall():
            key = f"{schema}.{table}"
            ref = f"{ref_schema}.{ref_table}.{ref_col}"
            fkeys.setdefault(key, []).append(SchemaForeignKey(column=col, ref=ref))
    return fkeys


def _fetch_geometry_columns() -> Dict[str, List[SchemaGeometry]]:
    sql = """
        select f_table_schema, f_table_name, f_geometry_column, srid
        from public.geometry_columns;
    """
    geometry: Dict[str, List[SchemaGeometry]] = {}
    try:
        with connection.cursor() as cur:
            cur.execute(sql)
            for schema, table, column, srid in cur.fetchall():
                key = f"{schema}.{table}"
                geometry.setdefault(key, []).append(SchemaGeometry(column=column, srid=srid))
    except Exception:
        # geometry_columns may not exist; leave geometry hints empty
        pass
    return geometry


def build_schema_index() -> Dict[str, object]:
    columns = _fetch_columns()
    fkeys = _fetch_foreign_keys()
    row_estimates = _fetch_row_estimates()
    geometry = _fetch_geometry_columns()

    tables: SchemaIndex = {}
    for table_key, cols in columns.items():
        tables[table_key] = SchemaTable(
            columns=cols,
            fkeys=fkeys.get(table_key, []),
            row_est=row_estimates.get(table_key),
            geometry=geometry.get(table_key, []),
        )

    return {
        "tables": tables,
        "built_at": int(time.time()),
    }


def _is_stale(cache: Dict[str, object]) -> bool:
    built_at = cache.get("built_at")
    if not isinstance(built_at, (int, float)):
        return True
    return (time.time() - built_at) > SCHEMA_MAX_AGE_SECONDS


def _load_cache_from_disk() -> Optional[Dict[str, object]]:
    if not SCHEMA_CACHE_PATH.exists():
        return None
    try:
        with SCHEMA_CACHE_PATH.open("r") as f:
            raw = json.load(f)
        # reconstruct dataclasses
        tables_raw = raw.get("tables") or {}
        tables: SchemaIndex = {}
        for key, info in tables_raw.items():
            tables[key] = SchemaTable(
                columns=[SchemaColumn(**col) for col in info.get("columns", [])],
                fkeys=[SchemaForeignKey(**fk) for fk in info.get("fkeys", [])],
                row_est=info.get("row_est"),
                geometry=[SchemaGeometry(**g) for g in info.get("geometry", [])],
            )
        return {"tables": tables, "built_at": raw.get("built_at")}
    except Exception:
        return None


def _save_cache_to_disk(cache: Dict[str, object]) -> None:
    tables_raw = {}
    for key, table_meta in cache["tables"].items():
        tables_raw[key] = {
            "columns": [col.__dict__ for col in table_meta.columns],
            "fkeys": [fk.__dict__ for fk in table_meta.fkeys],
            "row_est": table_meta.row_est,
            "geometry": [g.__dict__ for g in table_meta.geometry],
        }
    payload = {"tables": tables_raw, "built_at": cache.get("built_at")}
    try:
        _ensure_cache_dir()
        with SCHEMA_CACHE_PATH.open("w") as f:
            json.dump(payload, f)
    except OSError as exc:
        logger.warning(
            "Unable to write schema cache to %s: %s. Using in-memory cache only.",
            SCHEMA_CACHE_PATH,
            exc,
        )


def get_schema_index(force_refresh: bool = False) -> Dict[str, object]:
    global _memory_cache
    if not force_refresh and _memory_cache and not _is_stale(_memory_cache):
        return _memory_cache

    if not force_refresh:
        disk_cache = _load_cache_from_disk()
        if disk_cache and not _is_stale(disk_cache):
            _memory_cache = disk_cache
            return disk_cache

    fresh = build_schema_index()
    _save_cache_to_disk(fresh)
    _memory_cache = fresh
    return fresh
