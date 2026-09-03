"""Audit event queries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asynq_team_core.database import DatabaseConnection, DatabaseRow, connect_database
from asynq_team_core.tasks import get_task


@dataclass(frozen=True)
class AuditEvent:
    """A persisted audit event."""

    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor_type: str
    actor_id: str
    payload: dict[str, Any]
    created_at: str


def list_task_audit_events(
    database_path: Path,
    task_id: str,
    limit: int = 100,
) -> list[AuditEvent]:
    """Return audit events related to a task, ordered oldest first."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")

    with connect_database(database_path) as connection:
        if get_task(connection, task_id) is None:
            raise ValueError(f"Task not found: {task_id}")
        entity_keys = _task_entity_keys(connection, task_id)
        return _list_events_for_entities(connection, entity_keys, limit=limit)


def _task_entity_keys(connection: DatabaseConnection, task_id: str) -> tuple[tuple[str, str], ...]:
    keys: list[tuple[str, str]] = [("task", task_id)]
    keys.extend(("run", run_id) for run_id in _run_ids_for_task(connection, task_id))
    keys.extend(
        ("comment", comment_id) for comment_id in _comment_ids_for_task(connection, task_id)
    )
    keys.extend(
        ("approval", approval_id)
        for approval_id in _approval_ids_for_task(connection, task_id)
    )
    return tuple(keys)


def _run_ids_for_task(connection: DatabaseConnection, task_id: str) -> list[str]:
    rows = connection.execute("select id from runs where task_id = ?", (task_id,)).fetchall()
    return [row["id"] for row in rows]


def _comment_ids_for_task(connection: DatabaseConnection, task_id: str) -> list[str]:
    rows = connection.execute("select id from comments where task_id = ?", (task_id,)).fetchall()
    return [row["id"] for row in rows]


def _approval_ids_for_task(connection: DatabaseConnection, task_id: str) -> list[str]:
    rows = connection.execute(
        "select id from approvals where subject_type = ? and subject_id = ?",
        ("task", task_id),
    ).fetchall()
    return [row["id"] for row in rows]


def _list_events_for_entities(
    connection: DatabaseConnection,
    entity_keys: tuple[tuple[str, str], ...],
    limit: int,
) -> list[AuditEvent]:
    clauses = " or ".join("(entity_type = ? and entity_id = ?)" for _ in entity_keys)
    params: list[str | int] = []
    for entity_type, entity_id in entity_keys:
        params.extend((entity_type, entity_id))
    params.append(limit)

    rows = connection.execute(
        f"select * from events where {clauses} order by created_at asc, id asc limit ?",
        tuple(params),
    ).fetchall()

    return [_audit_event_from_row(row) for row in rows]


def _audit_event_from_row(row: DatabaseRow) -> AuditEvent:
    return AuditEvent(
        id=row["id"],
        event_type=row["type"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        actor_type=row["actor_type"],
        actor_id=row["actor_id"],
        payload=json.loads(row["payload_json"]),
        created_at=row["created_at"],
    )
