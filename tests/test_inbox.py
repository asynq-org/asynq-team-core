from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import (
    InboxItemStatus,
    InboxItemType,
    complete_inbox_item,
    create_inbox_item,
    get_inbox_item,
    list_inbox_items,
)


def test_create_inbox_item_persists_item_and_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        item = create_inbox_item(
            connection,
            recipient_id="founder",
            item_type=InboxItemType.QUESTION,
            title="Need input",
            body="Which repo should be public?",
            actor_type="agent",
            actor_id="ea",
            source_type="task",
            source_id="TASK-0001",
            clock=lambda: datetime(2026, 8, 24, 12, 30, 0, tzinfo=UTC),
        )
        loaded = get_inbox_item(connection, item.id)
        event = connection.execute(
            "select * from events where entity_type = ? and entity_id = ?",
            ("inbox_item", item.id),
        ).fetchone()

    assert item.id == "INBOX-0001"
    assert loaded == item
    assert item.status is InboxItemStatus.OPEN
    assert event["type"] == "inbox_item.created"


def test_list_inbox_items_filters_by_recipient_and_status(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        founder_item = create_inbox_item(
            connection,
            recipient_id="founder",
            item_type=InboxItemType.QUESTION,
            title="Need input",
            body="Choose a repo.",
            actor_type="agent",
            actor_id="ea",
        )
        create_inbox_item(
            connection,
            recipient_id="engineer",
            item_type=InboxItemType.BLOCKED_TASK,
            title="Blocked",
            body="Tests need credentials.",
            actor_type="agent",
            actor_id="george",
        )

        items = list_inbox_items(connection, recipient_id="founder")

    assert items == [founder_item]


def test_complete_inbox_item_marks_done_and_records_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        item = create_inbox_item(
            connection,
            recipient_id="founder",
            item_type=InboxItemType.QUESTION,
            title="Need input",
            body="Choose a repo.",
            actor_type="agent",
            actor_id="ea",
        )
        completed = complete_inbox_item(
            connection,
            item.id,
            actor_type="human",
            actor_id="founder",
        )
        open_items = list_inbox_items(connection)
        done_items = list_inbox_items(connection, status=InboxItemStatus.DONE)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("inbox_item.completed", item.id),
        ).fetchone()

    assert completed.status is InboxItemStatus.DONE
    assert open_items == []
    assert done_items == [completed]
    assert event is not None


def test_create_inbox_item_rejects_empty_title(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="title"),
    ):
        create_inbox_item(
            connection,
            recipient_id="founder",
            item_type=InboxItemType.QUESTION,
            title="",
            body="Choose a repo.",
            actor_type="agent",
            actor_id="ea",
        )
