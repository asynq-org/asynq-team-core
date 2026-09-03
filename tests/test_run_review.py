from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemType, list_inbox_items
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.run_review import RunReviewDecision, review_run
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.runs import RunStatus, update_run_status
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
