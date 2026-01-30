"""Helper for running schema-backed agents with tool guards."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Type, Union

from pydantic import BaseModel, ValidationError

from . import tools as agent_tools

logger = logging.getLogger(__name__)


AgentHandler = Callable[[BaseModel, Mapping[str, Callable[..., Any]]], Union[BaseModel, dict[str, Any]]]


class AgentExecutionError(RuntimeError):
    """Wraps errors surfaced while executing an agent."""


def collect_tools(allowed_names: Iterable[str]) -> Dict[str, Callable[..., Any]]:
    """Return the tool registry filtered to the permitted subset."""

    return agent_tools.allowed_tools(tuple(allowed_names))


def run_agent(
    *,
    agent_name: str,
    handler: AgentHandler,
    input_model: BaseModel,
    output_schema: Type[BaseModel],
    tools_allowed: Iterable[str],
) -> BaseModel:
    """
    Execute an agent handler and validate its output.

    The handler receives the parsed input model and the allowed tool subset.
    """

    toolset = collect_tools(tools_allowed)

    try:
        raw_output = handler(input_model, toolset)
    except Exception as exc:
        message = f"{agent_name} failed during execution: {exc}"
        logger.exception(message)
        raise AgentExecutionError(message) from exc

    if isinstance(raw_output, BaseModel):
        return raw_output

    try:
        return output_schema.parse_obj(raw_output)
    except ValidationError as exc:
        message = f"{agent_name} returned invalid output: {exc}"
        logger.exception(message)
        raise AgentExecutionError(message) from exc
