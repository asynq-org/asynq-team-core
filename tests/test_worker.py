from pathlib import Path

import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.runs import RunStatus, list_runs
from asynq_team_core.task_service import create_task_with_brief
from asynq_team_core.tasks import TaskStatus, get_task
from asynq_team_core.worker import run_worker_once


def test_run_worker_once_starts_next_task_run(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path)

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
    )

    assert result.task is not None
    assert result.task.id == "TASK-0001"
    assert result.task.status is TaskStatus.IN_PROGRESS
    assert result.started is not None
    assert result.started.work_packet.run.status is RunStatus.WORKING
    assert result.started.work_packet.artifact.relative_path == ".team/runs/george/RUN-0001/work.md"

    with connect_database(layout.database_path) as connection:
        stored_task = get_task(connection, "TASK-0001")
        runs = list_runs(connection)

    assert stored_task is not None
    assert stored_task.status is TaskStatus.IN_PROGRESS
    assert [run.id for run in runs] == ["RUN-0001"]


def test_run_worker_once_returns_empty_when_no_task_is_available(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
    )

    assert result.task is None
    assert result.authorization is None
    assert result.started is None


def test_run_worker_once_returns_approval_without_starting_run(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path)
    _replace_engineer_artifact_create_policy(layout, "require_approval")

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
    )

    with connect_database(layout.database_path) as connection:
        stored_task = get_task(connection, "TASK-0001")
        runs = list_runs(connection)
        approvals = list_approvals(connection)

    assert result.task is not None
    assert result.authorization is not None
    assert result.authorization.approval_request is not None
    assert result.started is None
    assert stored_task is not None
    assert stored_task.status is TaskStatus.CREATED
    assert runs == []
    assert approvals == [result.authorization.approval_request.approval]


def _create_workspace(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)
    return layout


def _create_workspace_with_task(tmp_path: Path):
    layout = _create_workspace(tmp_path)
    create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    )
    return layout


def _replace_engineer_artifact_create_policy(layout, target: str) -> None:
    path = layout.policy_dir / "capabilities.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    engineer = data["roles"]["engineer"]
    for field in ("allow", "require_approval", "deny"):
        engineer[field] = [item for item in engineer.get(field, []) if item != "artifact.create"]
    engineer.setdefault(target, []).append("artifact.create")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
