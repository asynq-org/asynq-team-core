"""Task comments and mentions for agent communication."""

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
from asynq_team_core.inbox import InboxItem, InboxItemType, create_inbox_item
from asynq_team_core.tasks import get_task


class CommentMentionStatus(str, Enum):
    """Supported comment mention statuses."""

    OPEN = "open"
    DONE = "done"


@dataclass(frozen=True)
class Comment:
    """A comment attached to a task."""

    id: str
    task_id: str
    author_type: str
    author_id: str
    body: str
    created_at: str


@dataclass(frozen=True)
class CommentMention:
    """A mention created from a comment."""

    id: str
    comment_id: str
    recipient_id: str
    status: CommentMentionStatus
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True)
class CommentCreation:
    """Result of creating a comment and its mentions."""

    comment: Comment
    mentions: tuple[CommentMention, ...]
    inbox_items: tuple[InboxItem, ...]


def create_task_comment(
    connection: DatabaseConnection,
    task_id: str,
    body: str,
    author_type: str,
    author_id: str,
    mentions: tuple[str, ...] = (),
    clock: Clock = utc_now,
) -> CommentCreation:
    """Create a task comment, mention records, inbox items, and audit events."""
    clean_task_id = _require_existing_task(connection, task_id)
    created_at = format_event_time(clock())
    comment = Comment(
        id=get_next_sequential_id(connection, "comments", "CMT"),
        task_id=clean_task_id,
        author_type=_require_non_empty(author_type, "author_type"),
        author_id=_require_non_empty(author_id, "author_id"),
        body=_require_non_empty(body, "body"),
        created_at=created_at,
    )

    connection.execute(
        """
        insert into comments (
            id,
            task_id,
            author_type,
            author_id,
            body,
            created_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            comment.id,
            comment.task_id,
            comment.author_type,
            comment.author_id,
            comment.body,
            comment.created_at,
        ),
    )

    clean_mentions = _dedupe_mentions(mentions)
    created_mentions = tuple(
        _create_comment_mention(
            connection,
            comment=comment,
            recipient_id=recipient_id,
            clock=lambda: _parse_event_time(created_at),
        )
        for recipient_id in clean_mentions
    )
    inbox_items = tuple(
        create_inbox_item(
            connection,
            recipient_id=mention.recipient_id,
            item_type=InboxItemType.MENTION,
            title=f"Mention on {comment.task_id}",
            body=comment.body,
            actor_type=comment.author_type,
            actor_id=comment.author_id,
            source_type="comment",
            source_id=comment.id,
            clock=lambda: _parse_event_time(created_at),
        )
        for mention in created_mentions
    )

    insert_event(
        connection,
        create_event(
            event_type="comment.created",
            entity_type="comment",
            entity_id=comment.id,
            actor_type=comment.author_type,
            actor_id=comment.author_id,
            payload={
                "task_id": comment.task_id,
                "mentions": [mention.recipient_id for mention in created_mentions],
            },
            clock=lambda: _parse_event_time(created_at),
        ),
    )

    return CommentCreation(
        comment=comment,
        mentions=created_mentions,
        inbox_items=inbox_items,
    )


def get_comment(connection: DatabaseConnection, comment_id: str) -> Comment | None:
    """Return a comment by id."""
    row = connection.execute("select * from comments where id = ?", (comment_id,)).fetchone()
    if row is None:
        return None
    return _comment_from_row(row)


def list_task_comments(
    connection: DatabaseConnection,
    task_id: str,
    limit: int = 50,
) -> list[Comment]:
    """Return comments for a task ordered from oldest to newest."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")

    rows = connection.execute(
        """
        select * from comments
        where task_id = ?
        order by created_at asc, id asc
        limit ?
        """,
        (_require_non_empty(task_id, "task_id"), limit),
    ).fetchall()

    return [_comment_from_row(row) for row in rows]


def list_comment_mentions(
    connection: DatabaseConnection,
    recipient_id: str | None = None,
    status: CommentMentionStatus | None = CommentMentionStatus.OPEN,
    limit: int = 50,
) -> list[CommentMention]:
    """Return comment mentions ordered from newest to oldest."""
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
        f"select * from comment_mentions{where} order by created_at desc, id desc limit ?",
        tuple(params),
    ).fetchall()

    return [_mention_from_row(row) for row in rows]


def _create_comment_mention(
    connection: DatabaseConnection,
    comment: Comment,
    recipient_id: str,
    clock: Clock,
) -> CommentMention:
    created_at = format_event_time(clock())
    mention = CommentMention(
        id=get_next_sequential_id(connection, "comment_mentions", "MNT"),
        comment_id=comment.id,
        recipient_id=recipient_id,
        status=CommentMentionStatus.OPEN,
        created_at=created_at,
        resolved_at=None,
    )

    connection.execute(
        """
        insert into comment_mentions (
            id,
            comment_id,
            recipient_id,
            status,
            created_at,
            resolved_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            mention.id,
            mention.comment_id,
            mention.recipient_id,
            mention.status.value,
            mention.created_at,
            mention.resolved_at,
        ),
    )
    insert_event(
        connection,
        create_event(
            event_type="comment.mentioned",
            entity_type="comment",
            entity_id=comment.id,
            actor_type=comment.author_type,
            actor_id=comment.author_id,
            payload={
                "mention_id": mention.id,
                "recipient_id": mention.recipient_id,
            },
            clock=lambda: _parse_event_time(created_at),
        ),
    )

    return mention


def _require_existing_task(connection: DatabaseConnection, task_id: str) -> str:
    clean_task_id = _require_non_empty(task_id, "task_id")
    if get_task(connection, clean_task_id) is None:
        raise ValueError(f"Task not found: {clean_task_id}")
    return clean_task_id


def _dedupe_mentions(mentions: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    clean_mentions: list[str] = []
    for mention in mentions:
        recipient_id = _require_non_empty(mention, "mention")
        if recipient_id in seen:
            continue
        seen.add(recipient_id)
        clean_mentions.append(recipient_id)
    return tuple(clean_mentions)


def _comment_from_row(row: DatabaseRow) -> Comment:
    return Comment(
        id=row["id"],
        task_id=row["task_id"],
        author_type=row["author_type"],
        author_id=row["author_id"],
        body=row["body"],
        created_at=row["created_at"],
    )


def _mention_from_row(row: DatabaseRow) -> CommentMention:
    return CommentMention(
        id=row["id"],
        comment_id=row["comment_id"],
        recipient_id=row["recipient_id"],
        status=CommentMentionStatus(row["status"]),
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
