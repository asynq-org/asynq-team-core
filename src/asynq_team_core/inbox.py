"""Inbox items for human and agent attention."""

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


class InboxItemStatus(str, Enum):
    """Supported inbox item statuses."""

    OPEN = "open"
    DONE = "done"


class InboxItemType(str, Enum):
    """Supported inbox item types."""

    APPROVAL = "approval"
    QUESTION = "question"
    BLOCKED_TASK = "blocked_task"
    REVIEW_RETURNED = "review_returned"


@dataclass(frozen=True)
class InboxItem:
    """A local attention item for a human or agent."""

    id: str
    recipient_id: str
    item_type: InboxItemType
    title: str
    body: str
    status: InboxItemStatus
    source_type: str | None
    source_id: str | None
    created_at: str
    updated_at: str


def create_inbox_item(
    connection: DatabaseConnection,
    recipient_id: str,
    item_type: InboxItemType,
    title: str,
    body: str,
    actor_type: str,
    actor_id: str,
    source_type: str | None = None,
    source_id: str | None = None,
    clock: Clock = utc_now,
) -> InboxItem:
    """Create an inbox item and record an audit event."""
    created_at = format_event_time(clock())
    item_id = get_next_sequential_id(connection, "inbox_items", "INBOX")
    item = InboxItem(
        id=item_id,
        recipient_id=_require_non_empty(recipient_id, "recipient_id"),
        item_type=item_type,
        title=_require_non_empty(title, "title"),
        body=_require_non_empty(body, "body"),
        status=InboxItemStatus.OPEN,
        source_type=source_type,
        source_id=source_id,
        created_at=created_at,
        updated_at=created_at,
    )

    connection.execute(
        """
        insert into agent_inbox (
            id,
            recipient_id,
            item_type,
            title,
            body,
            status,
            source_type,
            source_id,
            created_at,
            updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            item.recipient_id,
            item.item_type.value,
            item.title,
            item.body,
            item.status.value,
            item.source_type,
            item.source_id,
            item.created_at,
            item.updated_at,
        ),
    )
    insert_event(
        connection,
        create_event(
            event_type="inbox_item.created",
            entity_type="inbox_item",
            entity_id=item.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                "recipient_id": item.recipient_id,
                "item_type": item.item_type.value,
                "title": item.title,
                "source_type": item.source_type,
                "source_id": item.source_id,
            },
            clock=lambda: _parse_event_time(created_at),
        ),
    )

    return item


def get_inbox_item(connection: DatabaseConnection, item_id: str) -> InboxItem | None:
    """Return an inbox item by id."""
    row = connection.execute("select * from agent_inbox where id = ?", (item_id,)).fetchone()
    if row is None:
        return None
    return _inbox_item_from_row(row)


def list_inbox_items(
    connection: DatabaseConnection,
    recipient_id: str | None = None,
    status: InboxItemStatus | None = InboxItemStatus.OPEN,
    limit: int = 50,
) -> list[InboxItem]:
    """Return inbox items ordered by most recently updated first."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")

    clauses: list[str] = []
    params: list[str | int] = []
    if recipient_id is not None:
        clauses.append("recipient_id = ?")
        params.append(_require_non_empty(recipient_id, "recipient_id"))
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)

    where = f" where {' and '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = connection.execute(
        f"select * from agent_inbox{where} order by updated_at desc, id desc limit ?",
        tuple(params),
    ).fetchall()

    return [_inbox_item_from_row(row) for row in rows]


def complete_inbox_item(
    connection: DatabaseConnection,
    item_id: str,
    actor_type: str,
    actor_id: str,
    clock: Clock = utc_now,
) -> InboxItem:
    """Mark an inbox item as done and record an audit event."""
    item = get_inbox_item(connection, item_id)
    if item is None:
        raise ValueError(f"Inbox item not found: {item_id}")
    if item.status is InboxItemStatus.DONE:
        return item

    updated_at = format_event_time(clock())
    connection.execute(
        "update agent_inbox set status = ?, updated_at = ? where id = ?",
        (InboxItemStatus.DONE.value, updated_at, item.id),
    )
    insert_event(
        connection,
        create_event(
            event_type="inbox_item.completed",
            entity_type="inbox_item",
            entity_id=item.id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"previous_status": item.status.value},
            clock=lambda: _parse_event_time(updated_at),
        ),
    )

    completed = get_inbox_item(connection, item.id)
    if completed is None:
        raise RuntimeError(f"Inbox item disappeared after completion: {item.id}")
    return completed


def complete_inbox_items_for_source(
    connection: DatabaseConnection,
    source_type: str,
    source_id: str,
    actor_type: str,
    actor_id: str,
    clock: Clock = utc_now,
) -> tuple[InboxItem, ...]:
    """Mark all open inbox items for a source as done."""
    rows = connection.execute(
        """
        select id from agent_inbox
        where source_type = ? and source_id = ? and status = ?
        order by created_at asc, id asc
        """,
        (
            _require_non_empty(source_type, "source_type"),
            _require_non_empty(source_id, "source_id"),
            InboxItemStatus.OPEN.value,
        ),
    ).fetchall()

    return tuple(
        complete_inbox_item(
            connection,
            row["id"],
            actor_type=actor_type,
            actor_id=actor_id,
            clock=clock,
        )
        for row in rows
    )


def _inbox_item_from_row(row: DatabaseRow) -> InboxItem:
    return InboxItem(
        id=row["id"],
        recipient_id=row["recipient_id"],
        item_type=InboxItemType(row["item_type"]),
        title=row["title"],
        body=row["body"],
        status=InboxItemStatus(row["status"]),
        source_type=row["source_type"],
        source_id=row["source_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
