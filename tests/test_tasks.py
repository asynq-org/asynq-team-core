from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.database import (
    connect_database,
    get_applied_migration_versions,
    initialize_database,
)
from asynq_team_core.tasks import (
    TaskStatus,
    create_task,
    get_next_agent_task,
    get_next_unassigned_task,
    get_task,
    list_follow_up_tasks,
    list_tasks,
    update_task_assignee,
    update_task_status,
)


def test_initialize_database_applies_task_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"

    initialize_database(database_path)

    with connect_database(database_path) as connection:
        versions = get_applied_migration_versions(connection)

    assert versions == {1, 2, 3, 4, 5, 6, 7, 8}


def test_create_task_persists_task_and_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
            clock=lambda: datetime(2026, 8, 23, 12, 30, 0, tzinfo=UTC),
        )
        loaded = get_task(connection, task.id)
        event = connection.execute(
            "select * from events where entity_type = ? and entity_id = ?",
            ("task", task.id),
        ).fetchone()

    assert task.id == "TASK-0001"
    assert loaded == task
    assert event["type"] == "task.created"
    assert event["actor_id"] == "founder"


def test_create_task_can_use_preallocated_id(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
            task_id="TASK-0042",
        )

    assert task.id == "TASK-0042"


def test_create_task_can_link_parent_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        parent = create_task(
            connection,
            title="Parent task",
            actor_type="human",
            actor_id="founder",
        )
        follow_up = create_task(
            connection,
            title="Follow-up task",
            actor_type="agent",
            actor_id="george",
            parent_task_id=parent.id,
        )
        follow_ups = list_follow_up_tasks(connection, parent.id)

    assert follow_up.parent_task_id == parent.id
    assert follow_ups == [follow_up]


def test_list_tasks_filters_by_status(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        tasks = list_tasks(connection, status=TaskStatus.CREATED)

    assert tasks == [task]


def test_get_next_agent_task_returns_oldest_assigned_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        create_task(
            connection,
            title="Unassigned task",
            actor_type="human",
            actor_id="founder",
        )
        assigned = create_task(
            connection,
            title="Assigned task",
            actor_type="human",
            actor_id="founder",
            assignee_id="george",
        )
        next_task = get_next_agent_task(connection, "george")

    assert next_task == assigned


def test_get_next_agent_task_ignores_unassigned_and_other_agent_tasks(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        create_task(
            connection,
            title="Unassigned task",
            actor_type="human",
            actor_id="founder",
        )
        create_task(
            connection,
            title="Other agent task",
            actor_type="human",
            actor_id="founder",
            assignee_id="ea",
        )
        next_task = get_next_agent_task(connection, "george")

    assert next_task is None


def test_get_next_unassigned_task_returns_oldest_unassigned_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        first = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        create_task(
            connection,
            title="Assigned task",
            actor_type="human",
            actor_id="founder",
            assignee_id="george",
        )
        next_task = get_next_unassigned_task(connection)

    assert next_task == first


def test_update_task_status_persists_status_and_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        updated = update_task_status(
            connection,
            task_id=task.id,
            status=TaskStatus.IN_PROGRESS,
            actor_type="agent",
            actor_id="george",
        )
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("task.status_changed", task.id),
        ).fetchone()

    assert updated.status is TaskStatus.IN_PROGRESS
    assert event is not None


def test_update_task_status_returns_existing_task_when_status_is_unchanged(
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
        updated = update_task_status(
            connection,
            task_id=task.id,
            status=TaskStatus.CREATED,
            actor_type="agent",
            actor_id="george",
        )
        events = connection.execute(
            "select * from events where type = ?",
            ("task.status_changed",),
        ).fetchall()

    assert updated == task
    assert events == []


def test_update_task_status_rejects_missing_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="Task not found: TASK-9999"),
    ):
        update_task_status(
            connection,
            task_id="TASK-9999",
            status=TaskStatus.IN_PROGRESS,
            actor_type="agent",
            actor_id="george",
        )


def test_update_task_assignee_persists_assignee_and_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        updated = update_task_assignee(
            connection,
            task_id=task.id,
            assignee_id="george",
            actor_type="agent",
            actor_id="ea",
        )
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("task.assignee_changed", task.id),
        ).fetchone()

    assert updated.assignee_id == "george"
    assert event is not None
    assert event["actor_id"] == "ea"


def test_update_task_assignee_returns_existing_task_when_assignee_is_unchanged(
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
            assignee_id="george",
        )
        updated = update_task_assignee(
            connection,
            task_id=task.id,
            assignee_id="george",
            actor_type="agent",
            actor_id="ea",
        )
        events = connection.execute(
            "select * from events where type = ?",
            ("task.assignee_changed",),
        ).fetchall()

    assert updated == task
    assert events == []


def test_create_task_rejects_empty_title(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="title"),
    ):
        create_task(connection, title="", actor_type="human", actor_id="founder")
