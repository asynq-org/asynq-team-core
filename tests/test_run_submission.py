from pathlib import Path

import pytest
import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemType, list_inbox_items
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.run_submission import submit_authorized_run_for_review, submit_run_for_review
from asynq_team_core.runs import RunStatus, get_run, update_run_status
from asynq_team_core.task_service import create_task_with_brief


def test_submit_run_for_review_writes_result_and_mentions_reviewer(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path, status=RunStatus.WORKING)

    submission = submit_run_for_review(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        summary_md="Implemented the first pass.",
        checks_md="- poetry run pytest",
        reviewer_id="supervisor",
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        inbox_items = list_inbox_items(connection, recipient_id="supervisor")

    assert submission.run.status is RunStatus.WAITING_FOR_REVIEW
    assert submission.artifact.relative_path == ".team/runs/george/RUN-0001/result.md"
    result_body = submission.artifact.path.read_text(encoding="utf-8")
    assert "Implemented the first pass." in result_body
    assert "- poetry run pytest" in result_body
    assert submission.comment.comment.task_id == submission.task.id
    assert submission.comment.mentions[0].recipient_id == "supervisor"
    assert inbox_items[0].item_type is InboxItemType.MENTION
    assert inbox_items[0].source_id == submission.comment.comment.id


def test_submit_run_for_review_preserves_existing_result_by_default(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path, status=RunStatus.WORKING)
    submit_run_for_review(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        summary_md="Implemented the first pass.",
        reviewer_id="supervisor",
        actor_type="agent",
        actor_id="george",
    )
    with connect_database(layout.database_path) as connection:
        update_run_status(
            connection,
            run_id=run_id,
            status=RunStatus.RETURNED,
            actor_type="agent",
            actor_id="supervisor",
        )

    with pytest.raises(ValueError, match="Run result already exists"):
        submit_run_for_review(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            summary_md="Implemented the first pass again.",
            reviewer_id="supervisor",
            actor_type="agent",
            actor_id="george",
        )


def test_submit_run_for_review_rejects_created_run(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path, status=RunStatus.CREATED)

    with pytest.raises(ValueError, match="Run cannot be submitted from status: created"):
        submit_run_for_review(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            summary_md="Not ready.",
            reviewer_id="supervisor",
            actor_type="agent",
            actor_id="george",
        )


def test_submit_authorized_run_for_review_allows_default_engineer(tmp_path: Path) -> None:
    layout, run_id = _create_policy_workspace_run(tmp_path, status=RunStatus.WORKING)

    result = submit_authorized_run_for_review(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        summary_md="Implemented the first pass.",
        reviewer_id="supervisor",
        actor_type="agent",
        actor_id="george",
    )

    assert result.authorization is not None
    assert result.authorization.approval_request is None
    assert result.submission is not None
    assert result.submission.run.status is RunStatus.WAITING_FOR_REVIEW


def test_submit_authorized_run_for_review_requests_comment_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout, run_id = _create_policy_workspace_run(tmp_path, status=RunStatus.WORKING)
    _replace_role_comment_create_policy(layout, "engineer", "require_approval")

    result = submit_authorized_run_for_review(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        summary_md="Implemented the first pass.",
        reviewer_id="supervisor",
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        stored_run = get_run(connection, run_id)
        approvals = list_approvals(connection)

    assert result.authorization is not None
    assert result.authorization.approval_request is not None
    assert result.submission is None
    assert stored_run is not None
    assert stored_run.status is RunStatus.WORKING
    assert approvals == [result.authorization.approval_request.approval]
    assert not (layout.runs_dir / "george" / run_id / "result.md").exists()


def _create_workspace_run(tmp_path: Path, status: RunStatus) -> tuple[ProjectLayout, str]:
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

    if status is not RunStatus.CREATED:
        with connect_database(layout.database_path) as connection:
            run = update_run_status(
                connection,
                run_id=run.id,
                status=status,
                actor_type="agent",
                actor_id="george",
            )

    with connect_database(layout.database_path) as connection:
        loaded = get_run(connection, run.id)

    assert loaded is not None
    assert loaded.status is status
    return layout, run.id


def _create_policy_workspace_run(tmp_path: Path, status: RunStatus) -> tuple[ProjectLayout, str]:
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

    if status is not RunStatus.CREATED:
        with connect_database(layout.database_path) as connection:
            run = update_run_status(
                connection,
                run_id=run.id,
                status=status,
                actor_type="agent",
                actor_id="george",
            )

    return layout, run.id


def _replace_role_comment_create_policy(layout: ProjectLayout, role: str, target: str) -> None:
    path = layout.policy_dir / "capabilities.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    role_policy = data["roles"][role]
    for field in ("allow", "require_approval", "deny"):
        role_policy[field] = [item for item in role_policy.get(field, []) if item != "comment.create"]
    role_policy.setdefault(target, []).append("comment.create")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
