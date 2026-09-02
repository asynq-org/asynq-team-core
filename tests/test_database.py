from datetime import UTC, datetime
from pathlib import Path

from asynq_team_core.database import (
    connect_database,
    get_applied_migration_versions,
    initialize_database,
    insert_event,
)
from asynq_team_core.events import create_event


def test_initialize_database_applies_migrations(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"

    initialize_database(database_path)

    with connect_database(database_path) as connection:
        versions = get_applied_migration_versions(connection)
        events_table = connection.execute(
            "select name from sqlite_master where type = 'table' and name = 'events'"
        ).fetchone()

    assert versions == {1, 2, 3, 4, 5}
    assert events_table is not None


def test_insert_event_persists_event_record(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)
    event = create_event(
        event_type="task.created",
        entity_type="task",
        entity_id="TASK-0001",
        actor_type="human",
        actor_id="founder",
        payload={"title": "First task"},
        event_id="EVT-0001",
        clock=lambda: datetime(2026, 8, 23, 12, 30, 0, tzinfo=UTC),
    )

    with connect_database(database_path) as connection:
        insert_event(connection, event)
        row = connection.execute("select * from events where id = ?", ("EVT-0001",)).fetchone()

    assert row["type"] == "task.created"
    assert row["entity_id"] == "TASK-0001"
    assert row["payload_json"] == '{"title":"First task"}'
    assert row["hash"] == event.hash
