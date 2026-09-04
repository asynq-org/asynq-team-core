from pathlib import Path

import pytest

from asynq_team_core.audit import list_task_audit_events
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.run_files import RunFileChangeType, record_run_file_change
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.task_service import create_task_with_brief


def test_record_run_file_change_persists_file_event(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    record = record_run_file_change(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        relative_path="repos/core/src/example.py",
        change_type=RunFileChangeType.MODIFIED,
        additions=12,
        deletions=3,
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("run.file_changed", run_id),
        ).fetchone()

    assert record.run.id == run_id
    assert record.event.type == "run.file_changed"
    assert event is not None
    assert record.event.payload["path"] == "repos/core/src/example.py"
    assert record.event.payload["change_type"] == "modified"
    assert record.event.payload["additions"] == 12
    assert record.event.payload["deletions"] == 3


def test_record_run_file_change_appears_in_task_audit(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    record_run_file_change(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        relative_path="repos/core/src/example.py",
        change_type=RunFileChangeType.ADDED,
        actor_type="agent",
        actor_id="george",
    )

    events = list_task_audit_events(layout.database_path, "TASK-0001")

    assert "run.file_changed" in [event.event_type for event in events]


def test_record_run_file_change_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    with pytest.raises(ValueError, match="relative_path escapes the workspace"):
        record_run_file_change(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            relative_path="../outside.py",
            change_type=RunFileChangeType.MODIFIED,
            actor_type="agent",
            actor_id="george",
        )

    with pytest.raises(ValueError, match="relative_path must be relative"):
        record_run_file_change(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            relative_path="/tmp/outside.py",
            change_type=RunFileChangeType.MODIFIED,
            actor_type="agent",
            actor_id="george",
        )


def test_record_run_file_change_rejects_invalid_metadata(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    with pytest.raises(ValueError, match="additions must be non-negative"):
        record_run_file_change(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            relative_path="repos/core/src/example.py",
            change_type=RunFileChangeType.MODIFIED,
            additions=-1,
            actor_type="agent",
            actor_id="george",
        )


def test_record_run_file_change_rejects_missing_run(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    with pytest.raises(ValueError, match="Run not found: RUN-9999"):
        record_run_file_change(
            database_path=layout.database_path,
            layout=layout,
            run_id="RUN-9999",
            relative_path="repos/core/src/example.py",
            change_type=RunFileChangeType.MODIFIED,
            actor_type="agent",
            actor_id="george",
        )


def _create_workspace_run(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    task = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    ).task
    run = create_run_with_artifact_dir(
        database_path=layout.database_path,
        layout=layout,
        task_id=task.id,
        agent_id="george",
        actor_type="human",
        actor_id="founder",
    ).run

    return layout, run.id
