import sys
from pathlib import Path

import pytest

from asynq_team_core.audit import list_task_audit_events
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.runner_execution import (
    COMMAND_NOT_FOUND_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    execute_run_command,
)
from asynq_team_core.task_service import create_task_with_brief


def test_execute_run_command_runs_allowed_tool_and_records_audit(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    result = execute_run_command(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        tool="shell.test",
        command=(sys.executable, "-c", "print('ok')"),
        cwd=".",
        timeout_seconds=5,
        actor_type="agent",
        actor_id="george",
    )
    events = list_task_audit_events(layout.database_path, "TASK-0001")

    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.record.event.payload["tool"] == "shell.test"
    assert "run.command_executed" in [event.event_type for event in events]


def test_execute_run_command_rejects_denied_tool_without_audit(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    with pytest.raises(PermissionError, match="Runner tool is denied"):
        execute_run_command(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            tool="shell.destructive",
            command=(sys.executable, "-c", "print('unsafe')"),
            actor_type="agent",
            actor_id="george",
        )

    with connect_database(layout.database_path) as connection:
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("run.command_executed", run_id),
        ).fetchone()

    assert event is None


def test_execute_run_command_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    with pytest.raises(ValueError, match="cwd escapes the workspace"):
        execute_run_command(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            tool="shell.test",
            command=(sys.executable, "-c", "print('ok')"),
            cwd="../outside",
            actor_type="agent",
            actor_id="george",
        )


def test_execute_run_command_records_timeout(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    result = execute_run_command(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        tool="shell.test",
        command=(sys.executable, "-c", "import time; time.sleep(2)"),
        timeout_seconds=1,
        actor_type="agent",
        actor_id="george",
    )

    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.timed_out is True
    assert result.record.event.payload["exit_code"] == TIMEOUT_EXIT_CODE


def test_execute_run_command_records_missing_command(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    result = execute_run_command(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        tool="shell.test",
        command=("asynq-team-missing-runner-command",),
        timeout_seconds=1,
        actor_type="agent",
        actor_id="george",
    )

    assert result.exit_code == COMMAND_NOT_FOUND_EXIT_CODE
    assert result.stdout == ""
    assert "asynq-team-missing-runner-command" in result.stderr
    assert result.record.event.payload["exit_code"] == COMMAND_NOT_FOUND_EXIT_CODE


def _create_workspace_run(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
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
