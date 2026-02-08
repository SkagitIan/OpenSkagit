import json
import os
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from openai import OpenAI

from .schema_retriever import render_schema_context

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


SYSTEM_PROMPT = """
You are a cautious SQL builder for Postgres. Produce a single SELECT statement that answers the question using only the provided schema context.

Rules:
- Only one statement. No DDL/DML. No temp tables. No comments.
- Prefer aggregates for count/avg/sum questions.
- Always include a LIMIT (<= 500) on non-aggregate result sets.
- Do not use SELECT *; select only needed columns.
- Only use tables/columns listed in the provided schema context.
- When filtering by date ranges, be explicit (e.g., >= date '2024-01-01' AND < date '2025-01-01').
Respond as JSON with keys: sql (string), notes (array of strings), assumptions (array of strings).
""".strip()


def _build_user_prompt(question: str, schema_context: Dict[str, object]) -> str:
    schema_text = render_schema_context(schema_context) or "(no schema found)"
    return (
        f"Question:\n{question}\n\n"
        f"Schema context:\n{schema_text}\n\n"
        "Return JSON: {\"sql\": \"...\", \"notes\": [\"...\"], \"assumptions\": [\"...\"]}"
    )


def generate_sql(question: str, schema_context: Dict[str, object]) -> Dict[str, object]:
    model = os.environ.get("MCP_AGENT_SQL_MODEL", "gpt-4o-mini")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY")

    client = OpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(question, schema_context)},
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=float(os.environ.get("MCP_AGENT_SQL_TEMPERATURE", 0)),
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)

    sql = (payload.get("sql") or "").strip()
    if not sql:
        raise ValueError("LLM did not return SQL")

    def _clean_list(val) -> List[str]:
        if isinstance(val, list):
            return [str(v) for v in val]
        if not val:
            return []
        return [str(val)]

    return {
        "sql": sql,
        "notes": _clean_list(payload.get("notes")),
        "assumptions": _clean_list(payload.get("assumptions")),
        "model": model,
    }
