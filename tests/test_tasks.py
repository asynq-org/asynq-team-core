from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.database import (
    connect_database,
    get_applied_migration_versions,
    initialize_database,
)
from asynq_team_core.tasks import TaskStatus, create_task, get_task, list_tasks


def test_initialize_database_applies_task_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"

    initialize_database(database_path)

    with connect_database(database_path) as connection:
        versions = get_applied_migration_versions(connection)

    assert versions == {1, 2, 3, 4, 5}


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


def test_create_task_rejects_empty_title(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="title"),
    ):
        create_task(connection, title="", actor_type="human", actor_id="founder")
