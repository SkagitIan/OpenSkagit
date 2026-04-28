import re
from dataclasses import dataclass
from typing import Iterable, Optional, Set, Tuple

import sqlglot
from sqlglot import exp


DANGEROUS_PATTERNS = [
    r";",  # multi-statement / chaining
    r"\bcopy\b",
    r"\bcreate\b|\bdrop\b|\balter\b|\btruncate\b",
    r"\binsert\b|\bupdate\b|\bdelete\b",
    r"\bgrant\b|\brevoke\b",
    r"\bexecute\b|\bprepare\b|\bdeallocate\b",
    r"\bdblink\b",
    r"\bpg_read_file\b|\bpg_write_file\b|\bpg_ls_dir\b",
]

DEFAULT_ALLOW_SCHEMAS = {"public", "agent"}  # tighten if needed


@dataclass
class GuardConfig:
    allow_schemas: Set[str] = None
    allow_tables: Optional[Set[str]] = None  # if set, tables must match schema.table or table
    max_limit: int = 500
    explain_max_cost: float = 5_000_000  # tune
    explain_max_rows: float = 2_000_000  # tune

    def __post_init__(self):
        if self.allow_schemas is None:
            self.allow_schemas = set(DEFAULT_ALLOW_SCHEMAS)


def _has_danger(sql: str) -> Tuple[bool, str]:
    s = sql.strip().lower()
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, s):
            return True, f"Blocked by pattern: {pat}"
    return False, ""


def _tables_used(tree: exp.Expression) -> Iterable[Tuple[str, str]]:
    def _ident_to_str(value):
        if value is None:
            return None
        if isinstance(value, exp.Identifier):
            return value.name
        return str(value).strip() or None

    # returns (schema, table) where schema may be None
    for t in tree.find_all(exp.Table):
        db = _ident_to_str(t.args.get("db"))
        name = _ident_to_str(t.name)
        yield db, name


def validate_and_rewrite(sql: str, cfg: GuardConfig) -> str:
    bad, why = _has_danger(sql)
    if bad:
        raise ValueError(why)

    trees = sqlglot.parse(sql, dialect="postgres")
    if len(trees) != 1:
        raise ValueError("Only single-statement SELECTs are allowed")
    tree = trees[0]

    # SELECT-only at top-level
    root_select = tree
    if isinstance(tree, exp.With):
        root_select = tree.this
    if not isinstance(root_select, exp.Select):
        raise ValueError("Only SELECT queries are allowed")

    # forbid SELECT *
    if any(isinstance(node, exp.Star) for node in tree.find_all(exp.Star)):
        raise ValueError("SELECT * is not allowed")

    # schema allowlist
    for schema, table in _tables_used(tree):
        if schema and schema not in cfg.allow_schemas:
            raise ValueError(f"Schema not allowed: {schema}.{table}")
        if cfg.allow_tables:
            table_key = f"{schema}.{table}" if schema else table
            if table_key not in cfg.allow_tables and table not in cfg.allow_tables:
                raise ValueError(f"Table not allowed: {table_key}")

    # enforce LIMIT unless it’s a single-row aggregate w/o FROM explosion
    target = root_select
    has_limit = target.args.get("limit") is not None
    clamp_limit = exp.Limit(expression=exp.Literal.number(cfg.max_limit))
    if not has_limit:
        target.set("limit", clamp_limit)
    else:
        lim = target.args["limit"].expression
        if isinstance(lim, exp.Literal) and lim.is_int:
            if int(lim.this) > cfg.max_limit:
                target.set("limit", clamp_limit)
        else:
            target.set("limit", clamp_limit)

    return tree.sql(dialect="postgres")


def extract_table_names(sql: str) -> Set[str]:
    trees = sqlglot.parse(sql, dialect="postgres")
    if not trees:
        return set()
    names = set()
    for schema, table in _tables_used(trees[0]):
        names.add(f"{schema}.{table}" if schema else table)
    return names
