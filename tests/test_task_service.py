from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.task_service import create_task_with_brief
from asynq_team_core.tasks import get_task


def test_create_task_with_brief_writes_artifact_and_task_record(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    created = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
        clock=lambda: datetime(2026, 8, 23, 12, 30, 0, tzinfo=UTC),
    )

    with connect_database(layout.database_path) as connection:
        loaded = get_task(connection, created.task.id)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("task.created", created.task.id),
        ).fetchone()

    assert created.task.id == "TASK-0001"
    assert created.task.brief_artifact_path == ".team/tasks/TASK-0001/brief.md"
    assert created.brief.path.read_text(encoding="utf-8") == "Build the first task.\n"
    assert loaded == created.task
    assert event["entity_id"] == "TASK-0001"


def test_create_task_with_brief_rolls_back_counter_when_artifact_fails(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    write_protected_task_dir = layout.tasks_dir / "TASK-0001"
    write_protected_task_dir.mkdir()
    (write_protected_task_dir / "brief.md").write_text("Existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_task_with_brief(
            database_path=layout.database_path,
            layout=layout,
            title="First task",
            brief_md="Replacement",
            actor_type="human",
            actor_id="founder",
        )

    write_protected_task_dir.rename(layout.tasks_dir / "TASK-FAILED")
    created = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    )

    assert created.task.id == "TASK-0001"
