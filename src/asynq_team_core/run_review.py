"""Supervisor review workflows for runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from asynq_team_core.agent_manifests import load_agent_manifest
from asynq_team_core.artifact_policy import authorize_run_artifact_creation
from asynq_team_core.artifacts import ArtifactWrite, write_run_review, write_run_review_packet
from asynq_team_core.comments import (
    CommentCreation,
    authorize_task_comment_creation,
    create_task_comment,
)
from asynq_team_core.database import DatabaseRow, connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization, authorize_agent_capability
from asynq_team_core.runs import Run, RunStatus, get_run, update_run_status
from asynq_team_core.tasks import Task, TaskStatus, get_task, update_task_status


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
class RunReviewPacket:
    """Prepared work packet for an automated supervisor review."""

    run: Run
    task: Task
    artifact: ArtifactWrite


@dataclass(frozen=True)
class ParsedRunReviewOutput:
    """Structured review decision parsed from runner output."""

    decision: RunReviewDecision
    body_md: str


@dataclass(frozen=True)
class AuthorizedRunReview:
    """Result of an authorized run review attempt."""

    authorization: CapabilityAuthorization | None
    review: RunReview | None


def get_next_reviewable_run(
    database_path: Path,
    layout: ProjectLayout,
    reviewer_id: str,
) -> Run | None:
    """Return the oldest run waiting for the given reviewer."""
    clean_reviewer_id = _require_non_empty(reviewer_id, "reviewer_id")
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            select * from runs
            where status = ?
            order by updated_at asc, id asc
            """,
            (RunStatus.WAITING_FOR_REVIEW.value,),
        ).fetchall()

    for row in rows:
        run = _run_from_review_row(row)
        if _reviewer_id_for_agent(layout, run.agent_id) == clean_reviewer_id:
            return run
    return None


def prepare_run_review_packet(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    overwrite: bool = True,
) -> RunReviewPacket:
    """Prepare a review work packet for a submitted run."""
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

    artifact = write_run_review_packet(
        layout=layout,
        artifact_dir_path=run.artifact_dir_path,
        body_md=_render_review_packet(layout, run, task),
        overwrite=overwrite,
    )

    return RunReviewPacket(run=run, task=task, artifact=artifact)


def parse_run_review_output(output: str) -> ParsedRunReviewOutput:
    """Parse a supervisor runner response into a conservative review decision."""
    clean_output = _require_non_empty(output, "output")
    decision = _parse_review_output_decision(clean_output)
    body = _parse_review_output_body(clean_output)
    if decision is None:
        return ParsedRunReviewOutput(
            decision=RunReviewDecision.RETURN,
            body_md=(
                "Supervisor runner did not provide a valid `Decision:` line. "
                "Returning the run for explicit follow-up.\n\n"
                f"Raw output:\n\n```text\n{clean_output.rstrip()}\n```"
            ),
        )

    return ParsedRunReviewOutput(decision=decision, body_md=body)


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
        reviewed_task = update_task_status(
            connection,
            task_id=task.id,
            status=_task_status_for_decision(decision),
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
        task=reviewed_task,
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
    """Review a run after enforcing agent review, artifact, and comment capabilities."""
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

    authorization = authorize_run_artifact_creation(
        database_path=database_path,
        layout=layout,
        run=run,
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


def _render_review_packet(layout: ProjectLayout, run: Run, task: Task) -> str:
    result_artifact = _read_optional_run_artifact(layout, run.artifact_dir_path, "result.md")
    work_artifact = _read_optional_run_artifact(layout, run.artifact_dir_path, "work.md")
    return "\n".join(
        [
            f"# Run {run.id} Review Packet",
            "",
            "## Instructions",
            "Review the submitted run result and decide whether it is acceptable.",
            "Output must start with one of these exact lines:",
            "",
            "```text",
            "Decision: approve",
            "Decision: return",
            "```",
            "",
            "Then include `Review:` followed by concise Markdown feedback.",
            "",
            "## Task",
            f"- ID: {task.id}",
            f"- Title: {task.title}",
            f"- Status: {task.status.value}",
            "",
            "## Run",
            f"- ID: {run.id}",
            f"- Agent: {run.agent_id}",
            f"- Status: {run.status.value}",
            "",
            "## Submitted Result",
            result_artifact,
            "",
            "## Original Work Packet",
            work_artifact,
        ]
    )


def _read_optional_run_artifact(
    layout: ProjectLayout,
    artifact_dir_path: str | None,
    file_name: str,
) -> str:
    if artifact_dir_path is None:
        return "_No artifact directory found._"
    path = layout.workspace / artifact_dir_path / file_name
    _ensure_child_path(layout.runs_dir, path)
    if not path.is_file():
        return f"_No `{file_name}` artifact found._"
    return path.read_text(encoding="utf-8").rstrip()


def _parse_review_output_decision(output: str) -> RunReviewDecision | None:
    for line in output.splitlines():
        clean_line = line.strip()
        if not clean_line.lower().startswith("decision:"):
            continue
        value = clean_line.split(":", maxsplit=1)[1].strip().lower()
        if value == RunReviewDecision.APPROVE.value:
            return RunReviewDecision.APPROVE
        if value == RunReviewDecision.RETURN.value:
            return RunReviewDecision.RETURN
        return None
    return None


def _parse_review_output_body(output: str) -> str:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() == "review:":
            body = "\n".join(lines[index + 1 :]).strip()
            if body:
                return body
    return output.strip()


def _reviewer_id_for_agent(layout: ProjectLayout, agent_id: str) -> str:
    try:
        manifest = load_agent_manifest(layout, agent_id)
    except ValueError:
        return "founder"
    return manifest.supervisor or "founder"


def _run_from_review_row(row: DatabaseRow) -> Run:
    return Run(
        id=row["id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        status=RunStatus(row["status"]),
        artifact_dir_path=row["artifact_dir_path"],
        runner_id=row["runner_id"],
        model=row["model"],
        requested_model=row["requested_model"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Review artifact path escapes parent directory: {child}") from exc


def _status_for_decision(decision: RunReviewDecision) -> RunStatus:
    if decision is RunReviewDecision.APPROVE:
        return RunStatus.APPROVED
    if decision is RunReviewDecision.RETURN:
        return RunStatus.RETURNED
    raise ValueError(f"Unsupported review decision: {decision}")


def _task_status_for_decision(decision: RunReviewDecision) -> TaskStatus:
    if decision is RunReviewDecision.APPROVE:
        return TaskStatus.APPROVED
    if decision is RunReviewDecision.RETURN:
        return TaskStatus.RETURNED
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
