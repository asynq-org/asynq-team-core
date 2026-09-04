from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.task_service import create_follow_up_task, create_task_with_brief
from asynq_team_core.tasks import get_task, list_follow_up_tasks


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


def test_create_follow_up_task_links_parent_and_writes_brief(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    parent = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Parent task",
        brief_md="Build the parent task.",
        actor_type="human",
        actor_id="founder",
    ).task

    created = create_follow_up_task(
        database_path=layout.database_path,
        layout=layout,
        parent_task_id=parent.id,
        title="Follow-up task",
        brief_md="Capture the follow-up.",
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        loaded = get_task(connection, created.task.id)
        follow_ups = list_follow_up_tasks(connection, parent.id)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("task.followup_created", parent.id),
        ).fetchone()

    assert created.parent_task == parent
    assert created.task.id == "TASK-0002"
    assert created.task.parent_task_id == parent.id
    assert created.brief.path.read_text(encoding="utf-8") == "Capture the follow-up.\n"
    assert loaded == created.task
    assert follow_ups == [created.task]
    assert event is not None


def test_create_follow_up_task_rejects_missing_parent(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    with pytest.raises(ValueError, match="Parent task not found: TASK-9999"):
        create_follow_up_task(
            database_path=layout.database_path,
            layout=layout,
            parent_task_id="TASK-9999",
            title="Follow-up task",
            brief_md="Capture the follow-up.",
            actor_type="agent",
            actor_id="george",
        )
