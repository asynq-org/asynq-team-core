"""Run command audit recording."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.database import connect_database, insert_event
from asynq_team_core.events import Clock, Event, create_event, utc_now
from asynq_team_core.runs import Run, get_run


@dataclass(frozen=True)
class RunCommandRecord:
    """Recorded command execution metadata for a run."""

    run: Run
    event: Event


def record_run_command(
    database_path: Path,
    run_id: str,
    command: str,
    exit_code: int,
    actor_type: str,
    actor_id: str,
    cwd: str | None = None,
    duration_ms: int | None = None,
    tool: str | None = None,
    clock: Clock = utc_now,
) -> RunCommandRecord:
    """Record command execution metadata for a run without storing command output."""
    clean_command = _require_non_empty(command, "command")
    clean_exit_code = _require_int(exit_code, "exit_code")
    clean_duration_ms = _optional_non_negative_int(duration_ms, "duration_ms")
    clean_cwd = _optional_non_empty(cwd, "cwd")
    clean_tool = _optional_non_empty(tool, "tool")

    with connect_database(database_path) as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        event = create_event(
            event_type="run.command_executed",
            entity_type="run",
            entity_id=run.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "task_id": run.task_id,
                "agent_id": run.agent_id,
                "command": clean_command,
                "cwd": clean_cwd,
                "exit_code": clean_exit_code,
                "duration_ms": clean_duration_ms,
                "tool": clean_tool,
            },
            clock=clock,
        )
        insert_event(connection, event)

    return RunCommandRecord(run=run, event=event)


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_non_empty(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty(value, field_name)


def _require_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer.")
    return value


def _optional_non_negative_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    clean_value = _require_int(value, field_name)
    if clean_value < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return clean_value
