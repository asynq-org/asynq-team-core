"""Supervisor review workflows for runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from asynq_team_core.artifacts import ArtifactWrite, write_run_review
from asynq_team_core.comments import (
    CommentCreation,
    authorize_task_comment_creation,
    create_task_comment,
)
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization, authorize_agent_capability
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


@dataclass(frozen=True)
class AuthorizedRunReview:
    """Result of an authorized run review attempt."""

    authorization: CapabilityAuthorization | None
    review: RunReview | None


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


def review_authorized_run(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    decision: RunReviewDecision,
    body_md: str,
    actor_type: str,
    actor_id: str,
    overwrite: bool = False,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> AuthorizedRunReview:
    """Review a run after enforcing agent review and comment capabilities."""
    run, task = _load_reviewable_run(database_path, run_id)
    authorization = _authorize_agent_review_creation(
        database_path=database_path,
        layout=layout,
        run_id=run.id,
        actor_type=actor_type,
        actor_id=actor_id,
        approver_id=approver_id,
        clock=clock,
    )
    if authorization is not None and authorization.approval_request is not None:
        return AuthorizedRunReview(authorization=authorization, review=None)

    authorization = authorize_task_comment_creation(
        database_path=database_path,
        layout=layout,
        task_id=task.id,
        author_type=actor_type,
        author_id=actor_id,
        approver_id=approver_id,
        clock=clock,
    )
    if authorization is not None and authorization.approval_request is not None:
        return AuthorizedRunReview(authorization=authorization, review=None)

    review = review_run(
        database_path=database_path,
        layout=layout,
        run_id=run.id,
        decision=decision,
        body_md=body_md,
        actor_type=actor_type,
        actor_id=actor_id,
        overwrite=overwrite,
        clock=clock,
    )

    return AuthorizedRunReview(authorization=authorization, review=review)


def _authorize_agent_review_creation(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    actor_type: str,
    actor_id: str,
    approver_id: str,
    clock: Clock,
) -> CapabilityAuthorization | None:
    if actor_type != "agent":
        return None

    return authorize_agent_capability(
        database_path=database_path,
        layout=layout,
        agent_id=actor_id,
        capability="review.create",
        reason=f"Create review for run: {run_id}",
        approver_id=approver_id,
        subject_type="run",
        subject_id=run_id,
        clock=clock,
    )


def _load_reviewable_run(database_path: Path, run_id: str) -> tuple[Run, Task]:
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

    return run, task


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
