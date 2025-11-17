"""
Lightweight agent orchestration layer used by the prototype multi-agent system.
It mimics the bits of the OpenAI Agents SDK that we rely on (Agent + Runner)
so the project stays self-contained and runnable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional
import json


@dataclass
class ToolCall:
    """Simple record of a tool invocation for streaming + logging."""

    name: str
    args: Any
    output: Any

    def as_dict(self) -> Dict[str, Any]:
        def _safe(value: Any) -> Any:
            try:
                json.dumps(value)
                return value
            except TypeError:
                return str(value)

        return {
            "name": self.name,
            "args": _safe(self.args),
            "output": _safe(self.output),
        }


@dataclass
class AgentResult:
    message: str
    handoff: Optional[str]
    context_update: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop: bool = False


@dataclass
class AgentContext:
    state: Dict[str, Any]
    runner: "Runner"


@dataclass
class Agent:
    name: str
    instructions: str
    tools: Dict[str, Callable[..., Any]]
    handoffs: List[str]
    handler: Callable[[AgentContext], AgentResult]

    def run(self, context: AgentContext) -> AgentResult:
        return self.handler(context)


@dataclass
class StreamEvent:
    output_text: str


class Runner:
    """
    Sequential agent runner with logging + max-loop guardrails.
    """

    def __init__(self, *, max_loops: int = 5, log_path: Optional[Path] = None) -> None:
        self.max_loops = max_loops
        self.agents: Dict[str, Agent] = {}
        self.log_entries: List[Dict[str, Any]] = []
        default_log = Path(__file__).resolve().parent / "agent" / "outputs" / "iteration_log.json"
        self.log_path = log_path or default_log

    def register(self, agent: Agent) -> None:
        self.agents[agent.name] = agent

    def run(self, *, start_agent: str, initial_input: str) -> Generator[StreamEvent, None, None]:
        state: Dict[str, Any] = {
            "input": initial_input,
            "history": [],
            "loop_count": 0,
        }

        def _generator() -> Generator[StreamEvent, None, None]:
            current = start_agent
            while current:
                agent = self.agents.get(current)
                if agent is None:
                    yield StreamEvent(output_text=f"[Runner] Unknown agent '{current}'. Stopping.")
                    break

                yield StreamEvent(output_text=f"\n▶ {agent.name}: {agent.instructions}")

                context = AgentContext(state=state, runner=self)
                result = agent.run(context)
                state.update(result.context_update or {})
                state["history"].append(
                    {"agent": agent.name, "message": result.message, "handoff": result.handoff}
                )

                for call in result.tool_calls:
                    yield StreamEvent(
                        output_text=f"  • Tool {call.name} called with {call.args} → {str(call.output)[:120]}"
                    )

                yield StreamEvent(output_text=result.message)

                self._record_log(agent.name, result)

                if result.stop:
                    yield StreamEvent(output_text="✅ Workflow complete.")
                    break

                if result.handoff is None:
                    yield StreamEvent(output_text="⚠️ No next agent specified. Halting.")
                    break

                current = result.handoff

            self._flush_log()

        return _generator()

    # ------------------------------------------------------------------ #
    def _record_log(self, agent_name: str, result: AgentResult) -> None:
        entry = {
            "agent": agent_name,
            "message": result.message,
            "handoff": result.handoff,
            "stop": result.stop,
            "tool_calls": [call.as_dict() for call in result.tool_calls],
        }
        self.log_entries.append(entry)

    def _flush_log(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_entries, f, indent=2)
