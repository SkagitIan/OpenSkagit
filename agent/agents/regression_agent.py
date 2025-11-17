"""
Factory for RegressionAgent.
"""

from __future__ import annotations

from typing import Dict, Any, List

from agent_runtime import Agent, AgentContext, AgentResult, ToolCall
from tools.run_model import run_regression
from tools.diagnostics import compute_cod_prd
from tools.reporting import summarize_iteration

TARGET_COD = 10.0
TARGET_PRD_MIN = 0.98
TARGET_PRD_MAX = 1.03


def _build_rewrite_plan(metrics: Dict[str, float], recommendations: List[str]) -> Dict[str, Any]:
    changes: List[Dict[str, Any]] = []
    if metrics.get("COD", 0) >= TARGET_COD:
        changes.append({"parameter": "poly_degree", "value": 2})
        changes.append({"parameter": "ridge_alpha", "value": 0.1})
    prd = metrics.get("PRD")
    if prd is not None:
        if prd < TARGET_PRD_MIN:
            changes.append({"parameter": "interaction_weight", "value": 1.2})
            changes.append({"parameter": "include_interactions", "value": True})
        elif prd > TARGET_PRD_MAX:
            changes.append({"parameter": "interaction_weight", "value": 0.8})

    if not changes:
        changes.append({"parameter": "poly_degree", "value": 1})

    return {
        "focus_metrics": metrics,
        "changes": changes,
        "recommendations": recommendations,
    }


def create_regression_agent(code_agent: str) -> Agent:
    instructions = (
        "Evaluate regression performance (R², COD, PRD). "
        "If metrics meet thresholds (COD < 10 and 0.98 ≤ PRD ≤ 1.03), stop. "
        "Otherwise plan improvements and hand off to CodeRewriteAgent."
    )

    def handler(ctx: AgentContext) -> AgentResult:
        dataset_path = ctx.state.get("dataset_path")
        regression_results = run_regression(dataset_path)
        metrics = dict(regression_results)
        diagnostics = compute_cod_prd(dataset_path or "data/sample_data.csv")
        metrics.update({k: diagnostics[k] for k in ["COD", "PRD", "median_ratio"]})

        recommendations: List[str] = []
        if metrics["COD"] >= TARGET_COD:
            recommendations.append("Tighten fit by increasing polynomial terms or light regularization.")
        if metrics["PRD"] < TARGET_PRD_MIN:
            recommendations.append("Model is regressive; boost high-value predictions (interaction_weight ↑).")
        elif metrics["PRD"] > TARGET_PRD_MAX:
            recommendations.append("Model is progressive; dampen interaction effects (interaction_weight ↓).")

        summary = summarize_iteration(metrics, recommendations)
        meets_targets = metrics["COD"] < TARGET_COD and TARGET_PRD_MIN <= metrics["PRD"] <= TARGET_PRD_MAX

        tool_calls = [
            ToolCall(name="run_regression", args={"dataset_path": dataset_path}, output=regression_results),
            ToolCall(name="compute_cod_prd", args={"df_path": dataset_path}, output=diagnostics),
        ]

        context_update: Dict[str, Any] = {"latest_metrics": metrics}
        stop = False
        handoff = None
        message = summary

        if meets_targets:
            message += "\nMetrics within thresholds. RegressionAgent is satisfied."
            stop = True
        else:
            if ctx.state["loop_count"] >= ctx.runner.max_loops:
                message += f"\nLoop cap ({ctx.runner.max_loops}) reached. Stopping without code rewrite."
                stop = True
            else:
                ctx.state["loop_count"] += 1
                plan = _build_rewrite_plan(metrics, recommendations)
                context_update["rewrite_plan"] = plan
                handoff = code_agent
                message += "\nMetrics outside thresholds. Prepared rewrite plan for CodeRewriteAgent."

        return AgentResult(
            message=message,
            handoff=handoff,
            context_update=context_update,
            tool_calls=tool_calls,
            stop=stop,
        )

    return Agent(
        name="RegressionAgent",
        instructions=instructions,
        tools={
            "run_regression": run_regression,
            "compute_cod_prd": compute_cod_prd,
            "summarize_iteration": summarize_iteration,
        },
        handoffs=["CodeRewriteAgent"],
        handler=handler,
    )
