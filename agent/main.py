"""
Self-Improving Regression Analyst — powered by the mini agent runtime.
"""

from __future__ import annotations

from pathlib import Path

from agent_runtime import Runner
from agents.data_profiler_agent import create_data_profiler_agent
from agents.regression_agent import create_regression_agent
from agents.code_rewrite_agent import create_code_rewrite_agent

BASE_DIR = Path(__file__).resolve().parent


def build_runner() -> Runner:
    runner = Runner(max_loops=5, log_path=BASE_DIR / "outputs" / "iteration_log.json")

    # instantiate agents and register them with the runner
    regression_agent = create_regression_agent("CodeRewriteAgent")
    code_agent = create_code_rewrite_agent("RegressionAgent")
    data_agent = create_data_profiler_agent("RegressionAgent")

    runner.register(data_agent)
    runner.register(regression_agent)
    runner.register(code_agent)
    return runner


def main() -> None:
    runner = build_runner()
    session = runner.run(
        start_agent="DataProfilerAgent",
        initial_input="Begin profiling dataset at data/sample_data.csv and proceed as instructed.",
    )

    for event in session:
        print(event.output_text)


if __name__ == "__main__":
    main()
