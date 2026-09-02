from pathlib import Path

from asynq_team_core.database import initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.task_service import create_task_with_brief


def test_create_run_with_artifact_dir_creates_run_directory(tmp_path: Path) -> None:
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

    created = create_run_with_artifact_dir(
        database_path=layout.database_path,
        layout=layout,
        task_id=task.id,
        agent_id="george",
        actor_type="human",
        actor_id="founder",
    )

    assert created.run.id == "RUN-0001"
    assert created.run.artifact_dir_path == ".team/runs/george/RUN-0001"
    assert created.artifact_dir.is_dir()
