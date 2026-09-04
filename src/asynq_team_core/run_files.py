"""Run file-change audit recording."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from asynq_team_core.database import connect_database, insert_event
from asynq_team_core.events import Clock, Event, create_event, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runs import Run, get_run


class RunFileChangeType(str, Enum):
    """Supported file change categories for run audit records."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class RunFileChangeRecord:
    """Recorded file-change metadata for a run."""

    run: Run
    event: Event


def record_run_file_change(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    relative_path: str,
    change_type: RunFileChangeType,
    actor_type: str,
    actor_id: str,
    additions: int | None = None,
    deletions: int | None = None,
    previous_path: str | None = None,
    clock: Clock = utc_now,
) -> RunFileChangeRecord:
    """Record file-change metadata for a run without storing file contents."""
    clean_relative_path = _validate_workspace_relative_path(layout, relative_path, "relative_path")
    clean_previous_path = (
        _validate_workspace_relative_path(layout, previous_path, "previous_path")
        if previous_path is not None
        else None
    )
    clean_additions = _optional_non_negative_int(additions, "additions")
    clean_deletions = _optional_non_negative_int(deletions, "deletions")

    with connect_database(database_path) as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        event = create_event(
            event_type="run.file_changed",
            entity_type="run",
            entity_id=run.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "task_id": run.task_id,
                "agent_id": run.agent_id,
                "path": clean_relative_path,
                "previous_path": clean_previous_path,
                "change_type": change_type.value,
                "additions": clean_additions,
                "deletions": clean_deletions,
            },
            clock=clock,
        )
        insert_event(connection, event)

    return RunFileChangeRecord(run=run, event=event)


def _validate_workspace_relative_path(
    layout: ProjectLayout,
    value: str,
    field_name: str,
) -> str:
    clean_value = _require_non_empty(value, field_name)
    path = Path(clean_value)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative to the workspace.")

    resolved = layout.workspace / path
    _ensure_child_path(layout.workspace, resolved, field_name)
    return path.as_posix()


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_non_negative_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return value


def _ensure_child_path(parent: Path, child: Path, field_name: str) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"{field_name} escapes the workspace: {child}") from exc
