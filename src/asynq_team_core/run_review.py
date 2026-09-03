"""Supervisor review workflows for runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from asynq_team_core.artifacts import ArtifactWrite, write_run_review
from asynq_team_core.comments import CommentCreation, create_task_comment
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runs import Run, RunStatus, get_run, update_run_status
from asynq_team_core.tasks import Task, get_task


class RunReviewDecision(str, Enum):
    """Supported supervisor run review decisions."""

    APPROVE = "approve"
    RETURN = "return"


@dataclass(frozen=True)
class RunReview:
    """Result of reviewing a submitted run."""

    run: Run
    task: Task
    artifact: ArtifactWrite
    comment: CommentCreation
    decision: RunReviewDecision


def review_run(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    decision: RunReviewDecision,
    body_md: str,
    actor_type: str,
    actor_id: str,
    overwrite: bool = False,
    clock: Clock = utc_now,
) -> RunReview:
    """Write a run review artifact and update the run status."""
    clean_body = _require_non_empty(body_md, "body_md")

    with connect_database(database_path) as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        if run.artifact_dir_path is None:
            raise ValueError(f"Run has no artifact directory: {run.id}")
        if run.status is not RunStatus.WAITING_FOR_REVIEW:
            raise ValueError(f"Run cannot be reviewed from status: {run.status.value}")

        task = get_task(connection, run.task_id)
        if task is None:
            raise ValueError(f"Task not found for run {run.id}: {run.task_id}")

    artifact = write_run_review(
        layout=layout,
        artifact_dir_path=run.artifact_dir_path,
        body_md=_render_review(run, task, decision, clean_body),
        overwrite=overwrite,
    )
    next_status = _status_for_decision(decision)

    with connect_database(database_path) as connection:
        reviewed_run = update_run_status(
            connection,
            run_id=run.id,
            status=next_status,
            actor_type=actor_type,
            actor_id=actor_id,
            clock=clock,
        )
        comment = create_task_comment(
            connection,
            task_id=task.id,
            body=_render_review_comment(reviewed_run, decision, artifact, clean_body),
            author_type=actor_type,
            author_id=actor_id,
            mentions=(run.agent_id,),
            clock=clock,
        )

    return RunReview(
        run=reviewed_run,
        task=task,
        artifact=artifact,
        comment=comment,
        decision=decision,
    )


def _status_for_decision(decision: RunReviewDecision) -> RunStatus:
    if decision is RunReviewDecision.APPROVE:
        return RunStatus.APPROVED
    if decision is RunReviewDecision.RETURN:
        return RunStatus.RETURNED
    raise ValueError(f"Unsupported review decision: {decision}")


def _render_review(
    run: Run,
    task: Task,
    decision: RunReviewDecision,
    body_md: str,
) -> str:
    return "\n".join(
        [
            f"# Run {run.id} Review",
            "",
            "## Task",
            f"- ID: {task.id}",
            f"- Title: {task.title}",
            "",
            "## Decision",
            decision.value,
            "",
            "## Review",
            body_md.rstrip(),
        ]
    )


def _render_review_comment(
    run: Run,
    decision: RunReviewDecision,
    artifact: ArtifactWrite,
    body_md: str,
) -> str:
    summary_line = body_md.strip().splitlines()[0]
    return (
        f"@{run.agent_id} Review for {run.id}: {decision.value}.\n\n"
        f"Review: {artifact.relative_path}\n\n"
        f"Summary: {summary_line}"
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()
