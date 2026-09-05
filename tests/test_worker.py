import sys
from pathlib import Path

import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemStatus, list_inbox_items
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.runs import RunStatus, get_run, list_runs
from asynq_team_core.task_service import create_task_with_brief
from asynq_team_core.tasks import TaskStatus, get_task
from asynq_team_core.worker import route_next_unassigned_task, run_worker_once


def test_run_worker_once_starts_next_task_run(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path, assignee_id="george")

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


def test_run_worker_once_routes_unassigned_task_for_ea(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path)

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="ea",
    )

    with connect_database(layout.database_path) as connection:
        stored_task = get_task(connection, "TASK-0001")
        runs = list_runs(connection)

    assert result.routed is not None
    assert result.routed.assignee_id == "george"
    assert result.started is None
    assert stored_task is not None
    assert stored_task.assignee_id == "george"
    assert stored_task.status is TaskStatus.CREATED
    assert runs == []


def test_route_next_unassigned_task_routes_review_tasks_to_supervisor(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)
    create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Review implementation risk",
        brief_md="Review the current diff.",
        actor_type="human",
        actor_id="founder",
    )

    routed = route_next_unassigned_task(
        database_path=layout.database_path,
        layout=layout,
    )

    assert routed is not None
    assert routed.assignee_id == "supervisor"
    assert "supervisor" in routed.reason


def test_run_worker_once_returns_approval_without_starting_run(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path, assignee_id="george")
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


def test_run_worker_once_can_execute_runner_and_submit_for_review(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path, assignee_id="george")
    _replace_codex_command_template(layout, [sys.executable, "-c", "print('runner ok')"])

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
        execute_runner=True,
        runner_timeout_seconds=5,
    )

    assert result.execution is not None
    assert result.execution.exit_code == 0
    assert result.submission is not None
    assert result.submission.run.status is RunStatus.WAITING_FOR_REVIEW
    assert [mention.recipient_id for mention in result.submission.comment.mentions] == [
        "supervisor"
    ]
    assert result.submission.artifact.relative_path == ".team/runs/george/RUN-0001/result.md"
    assert "runner ok" in result.submission.artifact.path.read_text(encoding="utf-8")


def test_run_worker_once_blocks_task_when_runner_fails(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path, assignee_id="george")
    _replace_codex_command_template(layout, [sys.executable, "-c", "raise SystemExit(7)"])

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
        execute_runner=True,
        runner_timeout_seconds=5,
    )

    with connect_database(layout.database_path) as connection:
        stored_task = get_task(connection, "TASK-0001")
        stored_run = get_run(connection, "RUN-0001")

    assert result.execution is not None
    assert result.execution.exit_code == 7
    assert result.submission is None
    assert stored_run is not None
    assert stored_run.status is RunStatus.FAILED
    assert stored_task is not None
    assert stored_task.status is TaskStatus.BLOCKED


def test_run_worker_once_reviews_submitted_run_for_supervisor(tmp_path: Path) -> None:
    layout = _create_workspace_with_task(tmp_path, assignee_id="george")
    _replace_codex_command_template(
        layout,
        [sys.executable, "-c", "print('Decision: approve\\n\\nReview:\\nLooks ready.')"],
    )
    started = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
        execute_runner=True,
        runner_timeout_seconds=5,
    )

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="supervisor",
        execute_runner=True,
        runner_timeout_seconds=5,
    )

    with connect_database(layout.database_path) as connection:
        stored_task = get_task(connection, "TASK-0001")
        supervisor_inbox = list_inbox_items(
            connection,
            recipient_id="supervisor",
            status=InboxItemStatus.OPEN,
        )

    assert started.submission is not None
    assert result.review is not None
    assert result.review.execution is not None
    assert result.review.execution.exit_code == 0
    assert result.review.run_review is not None
    assert result.review.run_review.run.status is RunStatus.APPROVED
    assert result.review.review_packet_path == ".team/runs/george/RUN-0001/review-work.md"
    assert result.review.completed_inbox_items
    assert stored_task is not None
    assert stored_task.status is TaskStatus.APPROVED
    assert supervisor_inbox == []


def test_run_worker_once_keeps_review_waiting_when_supervisor_runner_fails(
    tmp_path: Path,
) -> None:
    layout = _create_workspace_with_task(tmp_path, assignee_id="george")
    _replace_codex_command_template(layout, [sys.executable, "-c", "print('runner ok')"])
    run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
        execute_runner=True,
        runner_timeout_seconds=5,
    )
    _replace_codex_command_template(layout, [sys.executable, "-c", "raise SystemExit(9)"])

    result = run_worker_once(
        database_path=layout.database_path,
        layout=layout,
        agent_id="supervisor",
        execute_runner=True,
        runner_timeout_seconds=5,
    )

    with connect_database(layout.database_path) as connection:
        stored_run = get_run(connection, "RUN-0001")

    assert result.review is not None
    assert result.review.execution is not None
    assert result.review.execution.exit_code == 9
    assert result.review.run_review is None
    assert stored_run is not None
    assert stored_run.status is RunStatus.WAITING_FOR_REVIEW


def _create_workspace(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)
    return layout


def _create_workspace_with_task(tmp_path: Path, assignee_id: str | None = None):
    layout = _create_workspace(tmp_path)
    create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
        assignee_id=assignee_id,
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


def _replace_codex_command_template(layout, command_template: list[str]) -> None:
    path = layout.policy_dir / "runners.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["runners"]["codex"]["command_template"] = command_template
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
