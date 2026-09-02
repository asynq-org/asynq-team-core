"""Agent run records and lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from asynq_team_core.database import (
    DatabaseConnection,
    DatabaseRow,
    get_next_sequential_id,
    insert_event,
)
from asynq_team_core.events import Clock, create_event, format_event_time, utc_now
from asynq_team_core.tasks import get_task


class RunStatus(str, Enum):
    """Supported MVP run statuses."""

    CREATED = "created"
    CLAIMED = "claimed"
    PLANNING = "planning"
    WORKING = "working"
    SELF_REVIEWING = "self_reviewing"
    WAITING_FOR_REVIEW = "waiting_for_review"
    RETURNED = "returned"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Run:
    """A local agent run record."""

    id: str
    task_id: str
    agent_id: str
    status: RunStatus
    artifact_dir_path: str | None
    created_at: str
    updated_at: str


def create_run(
    connection: DatabaseConnection,
    task_id: str,
    agent_id: str,
    actor_type: str,
    actor_id: str,
    run_id: str | None = None,
    artifact_dir_path: str | None = None,
    clock: Clock = utc_now,
) -> Run:
    """Create a run record for an existing task and record an audit event."""
    clean_task_id = _require_existing_task(connection, task_id)
    clean_agent_id = _require_non_empty(agent_id, "agent_id")
    created_at = format_event_time(clock())
    run = Run(
        id=run_id or get_next_sequential_id(connection, "runs", "RUN"),
        task_id=clean_task_id,
        agent_id=clean_agent_id,
        status=RunStatus.CREATED,
        artifact_dir_path=artifact_dir_path,
        created_at=created_at,
        updated_at=created_at,
    )

    connection.execute(
        """
        insert into runs (
            id,
            task_id,
            agent_id,
            status,
            artifact_dir_path,
            created_at,
            updated_at
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.id,
            run.task_id,
            run.agent_id,
            run.status.value,
            run.artifact_dir_path,
            run.created_at,
            run.updated_at,
        ),
    )
    insert_event(
        connection,
        create_event(
            event_type="run.created",
            entity_type="run",
            entity_id=run.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "task_id": run.task_id,
                "agent_id": run.agent_id,
                "artifact_dir_path": run.artifact_dir_path,
            },
            clock=lambda: _parse_event_time(created_at),
        ),
    )

    return run


def get_run(connection: DatabaseConnection, run_id: str) -> Run | None:
    """Return a run by id."""
    row = connection.execute("select * from runs where id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return _run_from_row(row)


def list_runs(
    connection: DatabaseConnection,
    task_id: str | None = None,
    agent_id: str | None = None,
    status: RunStatus | None = None,
    limit: int = 50,
) -> list[Run]:
    """Return runs ordered by most recently updated first."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")

    clauses: list[str] = []
    params: list[str | int] = []
    if task_id is not None:
        clauses.append("task_id = ?")
        params.append(_require_non_empty(task_id, "task_id"))
    if agent_id is not None:
        clauses.append("agent_id = ?")
        params.append(_require_non_empty(agent_id, "agent_id"))
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)

    where = f" where {' and '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = connection.execute(
        f"select * from runs{where} order by updated_at desc, id desc limit ?",
        tuple(params),
    ).fetchall()

    return [_run_from_row(row) for row in rows]


def update_run_status(
    connection: DatabaseConnection,
    run_id: str,
    status: RunStatus,
    actor_type: str,
    actor_id: str,
    clock: Clock = utc_now,
) -> Run:
    """Update a run status and record an audit event."""
    run = get_run(connection, run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    if run.status is status:
        return run

    updated_at = format_event_time(clock())
    connection.execute(
        "update runs set status = ?, updated_at = ? where id = ?",
        (status.value, updated_at, run.id),
    )
    insert_event(
        connection,
        create_event(
            event_type="run.status_changed",
            entity_type="run",
            entity_id=run.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "previous_status": run.status.value,
                "status": status.value,
            },
            clock=lambda: _parse_event_time(updated_at),
        ),
    )

    updated = get_run(connection, run.id)
    if updated is None:
        raise RuntimeError(f"Run disappeared after status update: {run.id}")
    return updated


def _require_existing_task(connection: DatabaseConnection, task_id: str) -> str:
    clean_task_id = _require_non_empty(task_id, "task_id")
    if get_task(connection, clean_task_id) is None:
        raise ValueError(f"Task not found: {clean_task_id}")
    return clean_task_id


def _run_from_row(row: DatabaseRow) -> Run:
    return Run(
        id=row["id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        status=RunStatus(row["status"]),
        artifact_dir_path=row["artifact_dir_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
