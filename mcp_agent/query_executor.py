import time
from pathlib import Path
from typing import Dict, List, Tuple

from django.db import connection
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def explain_json(sql: str) -> Dict:
    with connection.cursor() as cur:
        cur.execute("EXPLAIN (FORMAT JSON) " + sql)
        row = cur.fetchone()
    return row[0][0] if row else {}


def plan_is_expensive(plan: Dict, max_cost: float, max_rows: float) -> Tuple[bool, str]:
    if not plan:
        return False, ""
    try:
        root = plan.get("Plan", {})
        total_cost = root.get("Total Cost")
        plan_rows = root.get("Plan Rows")
        if total_cost and total_cost > max_cost:
            return True, f"Total cost {total_cost} exceeds {max_cost}"
        if plan_rows and plan_rows > max_rows:
            return True, f"Plan rows {plan_rows} exceeds {max_rows}"
    except Exception:
        pass
    return False, ""


def execute_sql(sql: str, statement_timeout_ms: int = 3000) -> Tuple[List[str], List[Tuple]]:
    with connection.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = %s", [statement_timeout_ms])
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
    return columns, rows


def timed_execute(sql: str, statement_timeout_ms: int = 3000) -> Tuple[int, List[str], List[Tuple]]:
    t0 = time.time()
    cols, rows = execute_sql(sql, statement_timeout_ms=statement_timeout_ms)
    elapsed_ms = int((time.time() - t0) * 1000)
    return elapsed_ms, cols, rows
