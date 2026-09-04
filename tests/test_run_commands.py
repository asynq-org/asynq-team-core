from pathlib import Path

import pytest

from asynq_team_core.audit import list_task_audit_events
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.run_commands import record_run_command
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.task_service import create_task_with_brief


def test_record_run_command_persists_command_event(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    record = record_run_command(
        database_path=layout.database_path,
        run_id=run_id,
        command="poetry run pytest",
        exit_code=0,
        cwd="repos/core",
        duration_ms=1250,
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("run.command_executed", run_id),
        ).fetchone()

    assert record.run.id == run_id
    assert record.event.type == "run.command_executed"
    assert event is not None
    assert record.event.payload["command"] == "poetry run pytest"
    assert record.event.payload["cwd"] == "repos/core"
    assert record.event.payload["exit_code"] == 0
    assert record.event.payload["duration_ms"] == 1250


def test_record_run_command_appears_in_task_audit(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    record_run_command(
        database_path=layout.database_path,
        run_id=run_id,
        command="poetry run ruff check .",
        exit_code=0,
        actor_type="agent",
        actor_id="george",
    )

    events = list_task_audit_events(layout.database_path, "TASK-0001")

    assert "run.command_executed" in [event.event_type for event in events]


def test_record_run_command_rejects_invalid_metadata(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    with pytest.raises(ValueError, match="command must be a non-empty string"):
        record_run_command(
            database_path=layout.database_path,
            run_id=run_id,
            command=" ",
            exit_code=0,
            actor_type="agent",
            actor_id="george",
        )

    with pytest.raises(ValueError, match="duration_ms must be non-negative"):
        record_run_command(
            database_path=layout.database_path,
            run_id=run_id,
            command="poetry run pytest",
            exit_code=0,
            duration_ms=-1,
            actor_type="agent",
            actor_id="george",
        )


def test_record_run_command_rejects_missing_run(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    with pytest.raises(ValueError, match="Run not found: RUN-9999"):
        record_run_command(
            database_path=layout.database_path,
            run_id="RUN-9999",
            command="poetry run pytest",
            exit_code=0,
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
