"""Runner adapter command planning and execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Formatter

from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runner_execution import RunnerExecution, execute_run_command
from asynq_team_core.runner_policy import RunnerAdapterConfig, load_runner_policy
from asynq_team_core.runs import Run

RUNNER_TOOL = "codex.runner"
ALLOWED_PLACEHOLDERS = frozenset(
    {
        "agent_id",
        "model",
        "run_id",
        "task_id",
        "workspace",
        "work_packet",
    }
)


@dataclass(frozen=True)
class RunnerCommandPlan:
    """Concrete command resolved from a runner adapter config."""

    runner_id: str
    tool: str
    command: tuple[str, ...]
    cwd: str


def execute_run_adapter_command(
    database_path: Path,
    layout: ProjectLayout,
    run: Run,
    work_packet_path: str,
    actor_type: str,
    actor_id: str,
    timeout_seconds: int = 300,
) -> RunnerExecution:
    """Execute a run through its configured runner adapter."""
    plan = plan_run_adapter_command(layout=layout, run=run, work_packet_path=work_packet_path)
    return execute_run_command(
        database_path=database_path,
        layout=layout,
        run_id=run.id,
        tool=plan.tool,
        command=plan.command,
        cwd=plan.cwd,
        timeout_seconds=timeout_seconds,
        actor_type=actor_type,
        actor_id=actor_id,
    )


def plan_run_adapter_command(
    layout: ProjectLayout,
    run: Run,
    work_packet_path: str,
) -> RunnerCommandPlan:
    """Resolve a concrete runner command for a run."""
    runner_id = _require_non_empty(run.runner_id, "run.runner_id")
    model = _require_non_empty(run.model, "run.model")
    work_packet = _require_non_empty(work_packet_path, "work_packet_path")
    config = _load_adapter_config(layout, runner_id)
    command = _render_command_template(
        config.command_template,
        {
            "agent_id": run.agent_id,
            "model": model,
            "run_id": run.id,
            "task_id": run.task_id,
            "workspace": layout.workspace.as_posix(),
            "work_packet": work_packet,
        },
    )

    return RunnerCommandPlan(
        runner_id=runner_id,
        tool=RUNNER_TOOL,
        command=command,
        cwd=config.working_directory,
    )


def _load_adapter_config(layout: ProjectLayout, runner_id: str) -> RunnerAdapterConfig:
    policy = load_runner_policy(layout)
    config = policy.adapters_by_runner.get(runner_id)
    if config is None:
        raise ValueError(f"Runner adapter is not configured: {runner_id}")
    if not config.command_template:
        raise ValueError(f"Runner command template is empty: {runner_id}")
    return config


def _render_command_template(
    template: tuple[str, ...],
    values: dict[str, str],
) -> tuple[str, ...]:
    return tuple(_render_template_part(part, values) for part in template)


def _render_template_part(part: str, values: dict[str, str]) -> str:
    formatter = Formatter()
    for _literal_text, field_name, _format_spec, conversion in formatter.parse(part):
        if field_name is None:
            continue
        if not field_name:
            raise ValueError("Runner command template placeholders must be named.")
        if field_name not in ALLOWED_PLACEHOLDERS:
            raise ValueError(f"Unknown runner command template placeholder: {field_name}")
        if conversion is not None:
            raise ValueError("Runner command template conversions are not supported.")

    return part.format_map(values)


def _require_non_empty(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()
