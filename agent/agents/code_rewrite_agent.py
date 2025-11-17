"""
Factory for CodeRewriteAgent.
"""

from __future__ import annotations

import json
from typing import Dict, Any

from agent_runtime import Agent, AgentContext, AgentResult, ToolCall
from tools.rewrite_code import rewrite_code
from tools.test_script import test_script
from tools.revert_tool import revert_last_change


def create_code_rewrite_agent(regression_agent: str) -> Agent:
    instructions = (
        "Edit regression_pipeline.py per the handoff context. Back up before editing. "
        "Run test_script. If it fails, revert. Hand back to RegressionAgent with test results."
    )

    def handler(ctx: AgentContext) -> AgentResult:
        plan: Dict[str, Any] = ctx.state.get("rewrite_plan")
        if not plan:
            message = "No rewrite plan available; skipping rewrite."
            return AgentResult(message=message, handoff=regression_agent, tool_calls=[])

        instruction_blob = json.dumps(plan, indent=2)
        rewrite_info = rewrite_code(instruction_blob)
        tests = test_script()

        tool_calls = [
            ToolCall(name="rewrite_code", args={"instructions": plan}, output=rewrite_info),
            ToolCall(name="test_script", args=None, output=tests),
        ]

        message = "Code updated and tests executed."
        if tests.get("success"):
            message += f" Metrics after rewrite: {tests.get('metrics')}"
        else:
            revert_info = revert_last_change()
            tool_calls.append(ToolCall(name="revert_last_change", args=None, output=revert_info))
            message += " Tests failed; reverted to previous backup."

        ctx.state.pop("rewrite_plan", None)
        return AgentResult(
            message=message,
            handoff=regression_agent,
            context_update={},
            tool_calls=tool_calls,
        )

    return Agent(
        name="CodeRewriteAgent",
        instructions=instructions,
        tools={
            "rewrite_code": rewrite_code,
            "test_script": test_script,
            "revert_last_change": revert_last_change,
        },
        handoffs=[regression_agent],
        handler=handler,
    )
