from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemType, list_inbox_items
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.run_submission import submit_run_for_review
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
