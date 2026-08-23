"""Task ledger models and persistence helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from asynq_team_core.database import get_next_sequential_id, insert_event
from asynq_team_core.events import Clock, create_event, format_event_time, utc_now


class TaskStatus(str, Enum):
    """Supported MVP task statuses."""

    CREATED = "created"
    TRIAGED = "triaged"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    RETURNED = "returned"
    APPROVED = "approved"
    READY_FOR_EXECUTION = "ready_for_execution"
    EXECUTED = "executed"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class Task:
    """A local task ledger entry."""

    id: str
    title: str
    status: TaskStatus
    priority: str
    assignee_id: Optional[str]
    brief_artifact_path: Optional[str]
    created_at: str
    updated_at: str


def create_task(
    connection: sqlite3.Connection,
    title: str,
    actor_type: str,
    actor_id: str,
    priority: str = "normal",
    assignee_id: Optional[str] = None,
    brief_artifact_path: Optional[str] = None,
    clock: Clock = utc_now,
) -> Task:
    """Create a task ledger entry and record a task.created event."""
    clean_title = _require_non_empty(title, "title")
    clean_priority = _require_non_empty(priority, "priority")
    created_at = format_event_time(clock())
    task_id = get_next_sequential_id(connection, "tasks", "TASK")

    task = Task(
        id=task_id,
        title=clean_title,
        status=TaskStatus.CREATED,
        priority=clean_priority,
        assignee_id=assignee_id,
        brief_artifact_path=brief_artifact_path,
        created_at=created_at,
        updated_at=created_at,
    )

    connection.execute(
        """
        insert into tasks (
            id,
            title,
            status,
            priority,
            assignee_id,
            brief_artifact_path,
            created_at,
            updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task.id,
            task.title,
            task.status.value,
            task.priority,
            task.assignee_id,
            task.brief_artifact_path,
            task.created_at,
            task.updated_at,
        ),
    )
    insert_event(
        connection,
        create_event(
            event_type="task.created",
            entity_type="task",
            entity_id=task.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "title": task.title,
                "priority": task.priority,
                "assignee_id": task.assignee_id,
                "brief_artifact_path": task.brief_artifact_path,
            },
            clock=lambda: _parse_event_time(created_at),
        ),
    )

    return task


def get_task(connection: sqlite3.Connection, task_id: str) -> Optional[Task]:
    """Return a task by id."""
    row = connection.execute("select * from tasks where id = ?", (task_id,)).fetchone()
    if row is None:
        return None
    return _task_from_row(row)


def list_tasks(
    connection: sqlite3.Connection,
    status: Optional[TaskStatus] = None,
    limit: int = 50,
) -> list[Task]:
    """Return tasks ordered by most recently updated first."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")

    if status is None:
        rows = connection.execute(
            "select * from tasks order by updated_at desc, id desc limit ?",
            (limit,),
        ).fetchall()
    else:
        rows = connection.execute(
            "select * from tasks where status = ? order by updated_at desc, id desc limit ?",
            (status.value, limit),
        ).fetchall()

    return [_task_from_row(row) for row in rows]


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        status=TaskStatus(row["status"]),
        priority=row["priority"],
        assignee_id=row["assignee_id"],
        brief_artifact_path=row["brief_artifact_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
