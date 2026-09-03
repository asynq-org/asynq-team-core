from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_task import start_task_run
from asynq_team_core.runs import RunStatus, get_run
from asynq_team_core.task_service import create_task_with_brief


def test_start_task_run_creates_run_and_work_packet(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path)

    started = start_task_run(
        database_path=layout.database_path,
        layout=layout,
        task_id="TASK-0001",
        agent_id="george",
        actor_type="agent",
        actor_id="george",
    )

    assert started.created.run.id == "RUN-0001"
    assert started.created.run.artifact_dir_path == ".team/runs/george/RUN-0001"
    assert started.work_packet.run.status is RunStatus.WORKING
    assert started.work_packet.artifact.relative_path == ".team/runs/george/RUN-0001/work.md"
    assert started.work_packet.artifact.path.is_file()
    assert "Build the first task." in started.work_packet.artifact.path.read_text(
        encoding="utf-8"
    )

    with connect_database(layout.database_path) as connection:
        stored = get_run(connection, "RUN-0001")

    assert stored is not None
    assert stored.status is RunStatus.WORKING


def test_start_task_run_rejects_missing_task(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path)

    with pytest.raises(ValueError, match="Task not found: TASK-9999"):
        start_task_run(
            database_path=layout.database_path,
            layout=layout,
            task_id="TASK-9999",
            agent_id="george",
            actor_type="agent",
            actor_id="george",
        )


def _create_workspace_with_task(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)
    create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    )

    return layout
