from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.backups import create_database_backup, list_database_backups
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout


def test_create_database_backup_writes_snapshot_and_event(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    backup = create_database_backup(
        database_path=layout.database_path,
        layout=layout,
        actor_type="human",
        actor_id="founder",
        clock=lambda: datetime(2026, 9, 4, 12, 30, 0, tzinfo=UTC),
    )

    with connect_database(layout.database_path) as connection:
        event = connection.execute(
            "select * from events where type = ?",
            ("database.backup_created",),
        ).fetchone()
    with connect_database(backup.path) as connection:
        versions = connection.execute("select version from schema_migrations").fetchall()

    assert backup.relative_path == ".team/backups/team-20260904T123000Z.db"
    assert backup.path.is_file()
    assert backup.size_bytes > 0
    assert event is not None
    assert len(versions) == 7


def test_list_database_backups_returns_newest_first(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    create_database_backup(
        database_path=layout.database_path,
        layout=layout,
        actor_type="human",
        actor_id="founder",
        clock=lambda: datetime(2026, 9, 4, 12, 30, 0, tzinfo=UTC),
    )
    create_database_backup(
        database_path=layout.database_path,
        layout=layout,
        actor_type="human",
        actor_id="founder",
        clock=lambda: datetime(2026, 9, 4, 12, 31, 0, tzinfo=UTC),
    )

    backups = list_database_backups(layout)

    assert [backup.relative_path for backup in backups] == [
        ".team/backups/team-20260904T123100Z.db",
        ".team/backups/team-20260904T123000Z.db",
    ]


def test_create_database_backup_rejects_missing_database(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)

    with pytest.raises(ValueError, match="Database is missing"):
        create_database_backup(
            database_path=layout.database_path,
            layout=layout,
            actor_type="human",
            actor_id="founder",
        )
