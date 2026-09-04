from pathlib import Path

import pytest
import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemType, list_inbox_items
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_review import RunReviewDecision, review_authorized_run, review_run
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.runs import RunStatus, get_run, update_run_status
from asynq_team_core.task_service import create_task_with_brief


def test_review_run_approves_submitted_run_and_mentions_agent(tmp_path: Path) -> None:
    layout, run_id = _create_submitted_run(tmp_path)

    review = review_run(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        decision=RunReviewDecision.APPROVE,
        body_md="Looks ready.",
        actor_type="agent",
        actor_id="supervisor",
    )

    with connect_database(layout.database_path) as connection:
        inbox_items = list_inbox_items(connection, recipient_id="george")

    assert review.run.status is RunStatus.APPROVED
    assert review.artifact.relative_path == ".team/runs/george/RUN-0001/review.md"
    assert "Looks ready." in review.artifact.path.read_text(encoding="utf-8")
    assert review.comment.mentions[0].recipient_id == "george"
    assert inbox_items[0].item_type is InboxItemType.MENTION
    assert inbox_items[0].source_id == review.comment.comment.id


def test_review_run_can_return_submitted_run(tmp_path: Path) -> None:
    layout, run_id = _create_submitted_run(tmp_path)

    review = review_run(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        decision=RunReviewDecision.RETURN,
        body_md="Please add missing tests.",
        actor_type="agent",
        actor_id="supervisor",
    )

    assert review.run.status is RunStatus.RETURNED
    assert "return" in review.artifact.path.read_text(encoding="utf-8")


def test_review_run_rejects_unsubmitted_run(tmp_path: Path) -> None:
    layout, run_id = _create_run(tmp_path)

    with pytest.raises(ValueError, match="Run cannot be reviewed from status: created"):
        review_run(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            decision=RunReviewDecision.APPROVE,
            body_md="Not submitted.",
            actor_type="agent",
            actor_id="supervisor",
        )


def test_review_authorized_run_allows_default_supervisor(tmp_path: Path) -> None:
    layout, run_id = _create_policy_submitted_run(tmp_path)

    result = review_authorized_run(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        decision=RunReviewDecision.APPROVE,
        body_md="Looks ready.",
        actor_type="agent",
        actor_id="supervisor",
    )

    assert result.authorization is not None
    assert result.authorization.approval_request is None
    assert result.review is not None
    assert result.review.run.status is RunStatus.APPROVED


def test_review_authorized_run_requests_comment_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout, run_id = _create_policy_submitted_run(tmp_path)
    _replace_role_comment_create_policy(layout, "supervisor", "require_approval")

    result = review_authorized_run(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        decision=RunReviewDecision.APPROVE,
        body_md="Looks ready.",
        actor_type="agent",
        actor_id="supervisor",
    )

    with connect_database(layout.database_path) as connection:
        stored_run = get_run(connection, run_id)
        approvals = list_approvals(connection)

    assert result.authorization is not None
    assert result.authorization.approval_request is not None
    assert result.review is None
    assert stored_run is not None
    assert stored_run.status is RunStatus.WAITING_FOR_REVIEW
    assert approvals == [result.authorization.approval_request.approval]
    assert not (layout.runs_dir / "george" / run_id / "review.md").exists()


def test_review_authorized_run_requests_review_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout, run_id = _create_policy_submitted_run(tmp_path)
    _replace_role_capability_policy(layout, "supervisor", "review.create", "require_approval")

    result = review_authorized_run(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        decision=RunReviewDecision.APPROVE,
        body_md="Looks ready.",
        actor_type="agent",
        actor_id="supervisor",
    )

    with connect_database(layout.database_path) as connection:
        stored_run = get_run(connection, run_id)
        approvals = list_approvals(connection)

    assert result.authorization is not None
    assert result.authorization.evaluation.capability == "review.create"
    assert result.authorization.approval_request is not None
    assert result.review is None
    assert stored_run is not None
    assert stored_run.status is RunStatus.WAITING_FOR_REVIEW
    assert approvals == [result.authorization.approval_request.approval]
    assert not (layout.runs_dir / "george" / run_id / "review.md").exists()


def test_review_authorized_run_rejects_denied_review_capability(tmp_path: Path) -> None:
    layout, run_id = _create_policy_submitted_run(tmp_path)
    _replace_role_capability_policy(layout, "supervisor", "review.create", "deny")

    with pytest.raises(PermissionError, match="denied for role"):
        review_authorized_run(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            decision=RunReviewDecision.APPROVE,
            body_md="Looks ready.",
            actor_type="agent",
            actor_id="supervisor",
        )


def _create_submitted_run(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout, run_id = _create_run(tmp_path)
    with connect_database(layout.database_path) as connection:
        update_run_status(
            connection,
            run_id=run_id,
            status=RunStatus.WAITING_FOR_REVIEW,
            actor_type="agent",
            actor_id="george",
        )

    return layout, run_id


def _create_run(tmp_path: Path) -> tuple[ProjectLayout, str]:
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


def _create_policy_submitted_run(tmp_path: Path) -> tuple[ProjectLayout, str]:
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
    with connect_database(layout.database_path) as connection:
        update_run_status(
            connection,
            run_id=run.id,
            status=RunStatus.WAITING_FOR_REVIEW,
            actor_type="agent",
            actor_id="george",
        )

    return layout, run.id


def _replace_role_comment_create_policy(layout: ProjectLayout, role: str, target: str) -> None:
    _replace_role_capability_policy(layout, role, "comment.create", target)


def _replace_role_capability_policy(
    layout: ProjectLayout,
    role: str,
    capability: str,
    target: str,
) -> None:
    path = layout.policy_dir / "capabilities.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    role_policy = data["roles"][role]
    for field in ("allow", "require_approval", "deny"):
        role_policy[field] = [item for item in role_policy.get(field, []) if item != capability]
    role_policy.setdefault(target, []).append(capability)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
