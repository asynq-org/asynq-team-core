from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.comments import (
    CommentMentionStatus,
    create_task_comment,
    get_comment,
    list_comment_mentions,
    list_task_comments,
)
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemType, list_inbox_items
from asynq_team_core.tasks import create_task


def test_create_task_comment_persists_comment_mentions_and_inbox_items(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        created = create_task_comment(
            connection,
            task_id=task.id,
            body="@supervisor Please review the plan.",
            author_type="agent",
            author_id="george",
            mentions=("supervisor", "supervisor"),
            clock=lambda: datetime(2026, 9, 2, 12, 30, 0, tzinfo=UTC),
        )
        loaded = get_comment(connection, created.comment.id)
        mentions = list_comment_mentions(connection, recipient_id="supervisor")
        inbox_items = list_inbox_items(connection, recipient_id="supervisor")
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("comment.created", created.comment.id),
        ).fetchone()

    assert created.comment.id == "CMT-0001"
    assert created.mentions[0].id == "MNT-0001"
    assert len(created.mentions) == 1
    assert loaded == created.comment
    assert mentions == list(created.mentions)
    assert inbox_items == list(created.inbox_items)
    assert inbox_items[0].item_type is InboxItemType.MENTION
    assert inbox_items[0].source_id == created.comment.id
    assert event is not None


def test_list_task_comments_returns_oldest_first(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        first = create_task_comment(
            connection,
            task_id=task.id,
            body="First comment.",
            author_type="human",
            author_id="founder",
            clock=lambda: datetime(2026, 9, 2, 12, 30, 0, tzinfo=UTC),
        )
        second = create_task_comment(
            connection,
            task_id=task.id,
            body="Second comment.",
            author_type="agent",
            author_id="george",
            clock=lambda: datetime(2026, 9, 2, 12, 31, 0, tzinfo=UTC),
        )

        comments = list_task_comments(connection, task.id)

    assert comments == [first.comment, second.comment]


def test_create_task_comment_rejects_missing_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="Task not found: TASK-9999"),
    ):
        create_task_comment(
            connection,
            task_id="TASK-9999",
            body="Missing task.",
            author_type="human",
            author_id="founder",
        )


def test_create_task_comment_rejects_empty_mention(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )

        with pytest.raises(ValueError, match="mention"):
            create_task_comment(
                connection,
                task_id=task.id,
                body="Invalid mention.",
                author_type="human",
                author_id="founder",
                mentions=("",),
            )


def test_list_comment_mentions_can_include_done_statuses(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        create_task_comment(
            connection,
            task_id=task.id,
            body="@supervisor Please review.",
            author_type="agent",
            author_id="george",
            mentions=("supervisor",),
        )

        mentions = list_comment_mentions(connection, status=CommentMentionStatus.OPEN)
        all_mentions = list_comment_mentions(connection, status=None)

    assert mentions == all_mentions
