"""
Factory for the DataProfilerAgent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from agent_runtime import Agent, AgentContext, AgentResult, ToolCall
from tools.data_probe import analyze_dataset
from tools.sql_writer import run_sql_query

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = BASE_DIR / "data" / "sample_data.csv"


def _build_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
    missing_flags = {col: pct for col, pct in profile["missing_pct"].items() if pct > 0}
    skew_flags = {col: val for col, val in profile["skewness"].items() if abs(val) > 0.5}
    return {
        "rows": profile["n_rows"],
        "columns": len(profile["missing_pct"]),
        "missing_columns": missing_flags,
        "skewed_columns": skew_flags,
        "top_correlations": sorted(
            profile["correlations"]
            .get("sale_price", {})
            .items(),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:3],
    }


def create_data_profiler_agent(next_agent: str) -> Agent:
    instructions = (
        "Inspect dataset health, missing data, skew, or correlations. "
        "Use SQL queries as needed. Once profiling is complete, "
        "hand off findings to RegressionAgent."
    )

    def handler(ctx: AgentContext) -> AgentResult:
        dataset_path = str(ctx.state.get("dataset_path") or DEFAULT_DATASET)
        ctx.state["dataset_path"] = dataset_path

        profile = analyze_dataset(dataset_path)
        sql_query = "SELECT AVG(sale_price) AS avg_sale_price, AVG(assessed_value) AS avg_assessed_value FROM sales"
        sql_snapshot = run_sql_query(sql_query, dataset_path=dataset_path)
        summary = _build_summary(profile)
        summary["sql_snapshot"] = sql_snapshot

        message = (
            "Profiling complete. "
            f"{summary['rows']} records with {summary['columns']} columns. "
            f"Missing columns: {list(summary['missing_columns'].keys()) or 'None'}. "
            f"High skew: {list(summary['skewed_columns'].keys()) or 'None'}."
        )

        tool_calls = [
            ToolCall(name="analyze_dataset", args={"path": dataset_path}, output=profile),
            ToolCall(name="run_sql_query", args={"query": sql_query}, output=sql_snapshot),
        ]

        return AgentResult(
            message=message,
            handoff=next_agent,
            context_update={"profile_summary": summary},
            tool_calls=tool_calls,
        )

    return Agent(
        name="DataProfilerAgent",
        instructions=instructions,
        tools={"analyze_dataset": analyze_dataset, "run_sql_query": run_sql_query},
        handoffs=[next_agent],
        handler=handler,
    )
