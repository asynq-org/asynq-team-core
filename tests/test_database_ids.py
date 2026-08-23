from pathlib import Path

from asynq_team_core.database import (
    connect_database,
    get_applied_migration_versions,
    get_next_sequential_id,
    initialize_database,
)


def test_initialize_database_applies_id_counter_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"

    initialize_database(database_path)

    with connect_database(database_path) as connection:
        versions = get_applied_migration_versions(connection)

    assert versions == {1, 2}


def test_get_next_sequential_id_uses_persistent_counter(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        first = get_next_sequential_id(connection, "tasks", "TASK")
        second = get_next_sequential_id(connection, "tasks", "TASK")

    assert first == "TASK-0001"
    assert second == "TASK-0002"
