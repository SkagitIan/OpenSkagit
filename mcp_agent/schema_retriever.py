import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

from .schema_index import SchemaIndex, SchemaTable, get_schema_index

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


SYNONYMS = {
    "sales": {"sale", "transaction", "transactions"},
    "parcel": {"parcels", "lot", "lots"},
    "tax": {"taxes", "taxation"},
    "zoning": {"zone", "zones"},
    "flood": {"sfha", "fema", "floodzone"},
}


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    expanded = []
    for tok in tokens:
        expanded.append(tok)
        for canon, alts in SYNONYMS.items():
            if tok == canon or tok in alts:
                expanded.append(canon)
    return expanded


def _score_table(question_tokens: Counter, table_name: str, table: SchemaTable) -> float:
    name_parts = _tokenize(table_name.replace(".", " "))
    column_tokens = []
    for col in table.columns:
        column_tokens.extend(_tokenize(col.name))
    table_counter = Counter(name_parts + column_tokens)

    overlap = sum(min(count, table_counter[token]) for token, count in question_tokens.items())

    # gentle penalty for very large tables to steer toward narrower ones when scores tie
    penalty = 0.0
    if table.row_est and table.row_est > 5_000_000:
        penalty = 0.5
    return overlap - penalty


def rank_tables(question: str, schema_index: SchemaIndex, limit: int = 8) -> List[Tuple[str, SchemaTable]]:
    tokens = Counter(_tokenize(question))
    scored: List[Tuple[str, float, SchemaTable]] = []
    for table_name, table in schema_index.items():
        score = _score_table(tokens, table_name, table)
        if score > 0:
            scored.append((table_name, score, table))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:limit]
    return [(name, tbl) for name, _, tbl in top]


def build_schema_context(question: str, max_tables: int = 8, force_refresh: bool = False) -> Dict[str, object]:
    index = get_schema_index(force_refresh=force_refresh)
    tables = index.get("tables", {})
    ranked = rank_tables(question, tables, limit=max_tables)
    context_tables: Dict[str, Dict[str, object]] = {}
    for table_name, table in ranked:
        context_tables[table_name] = {
            "columns": [{"name": c.name, "type": c.type} for c in table.columns],
            "fkeys": [{"column": fk.column, "ref": fk.ref} for fk in table.fkeys],
            "row_est": table.row_est,
            "geometry": [{"column": g.column, "srid": g.srid} for g in table.geometry],
        }
    return {"tables": context_tables}


def render_schema_context(context: Dict[str, object]) -> str:
    lines: List[str] = []
    tables: Dict[str, Dict[str, object]] = context.get("tables", {})  # type: ignore[assignment]
    for table_name, meta in tables.items():
        cols = ", ".join([f"{c['name']} ({c['type']})" for c in meta.get("columns", [])])
        row_est = meta.get("row_est")
        row_hint = f" ~{row_est} rows" if row_est else ""
        lines.append(f"{table_name}{row_hint}: {cols}")
    return "\n".join(lines)
