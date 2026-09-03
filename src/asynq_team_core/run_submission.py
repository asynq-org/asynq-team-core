"""Run submission workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.artifacts import ArtifactWrite, write_run_result
from asynq_team_core.comments import CommentCreation, create_task_comment
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runs import Run, RunStatus, get_run, update_run_status
from asynq_team_core.tasks import Task, get_task

REVIEW_SUBMITTABLE_STATUSES = frozenset(
    {
        RunStatus.WORKING,
        RunStatus.SELF_REVIEWING,
        RunStatus.RETURNED,
    }
)


@dataclass(frozen=True)
class RunSubmission:
    """Result of submitting a run for review."""

    run: Run
    task: Task
    artifact: ArtifactWrite
    comment: CommentCreation


def submit_run_for_review(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    summary_md: str,
    reviewer_id: str,
    actor_type: str,
    actor_id: str,
    checks_md: str | None = None,
    overwrite: bool = False,
    clock: Clock = utc_now,
) -> RunSubmission:
    """Write a run result artifact and request supervisor review."""
    clean_summary = _require_non_empty(summary_md, "summary_md")
    clean_reviewer_id = _require_non_empty(reviewer_id, "reviewer_id")

    with connect_database(database_path) as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        if run.artifact_dir_path is None:
            raise ValueError(f"Run has no artifact directory: {run.id}")
        if run.status not in REVIEW_SUBMITTABLE_STATUSES:
            raise ValueError(f"Run cannot be submitted from status: {run.status.value}")

        task = get_task(connection, run.task_id)
        if task is None:
            raise ValueError(f"Task not found for run {run.id}: {run.task_id}")

    artifact = write_run_result(
        layout=layout,
        artifact_dir_path=run.artifact_dir_path,
        body_md=_render_result(run, task, clean_summary, checks_md),
        overwrite=overwrite,
    )

    with connect_database(database_path) as connection:
        updated_run = update_run_status(
            connection,
            run_id=run.id,
            status=RunStatus.WAITING_FOR_REVIEW,
            actor_type=actor_type,
            actor_id=actor_id,
            clock=clock,
        )
        comment = create_task_comment(
            connection,
            task_id=task.id,
            body=_render_review_request(updated_run, artifact, clean_summary, clean_reviewer_id),
            author_type=actor_type,
            author_id=actor_id,
            mentions=(clean_reviewer_id,),
            clock=clock,
        )

    return RunSubmission(
        run=updated_run,
        task=task,
        artifact=artifact,
        comment=comment,
    )


def _render_result(
    run: Run,
    task: Task,
    summary_md: str,
    checks_md: str | None,
) -> str:
    sections = [
        f"# Run {run.id} Result",
        "",
        "## Task",
        f"- ID: {task.id}",
        f"- Title: {task.title}",
        "",
        "## Summary",
        summary_md.rstrip(),
        "",
        "## Checks",
        checks_md.rstrip() if checks_md and checks_md.strip() else "_No checks recorded._",
    ]

    return "\n".join(sections)


def _render_review_request(
    run: Run,
    artifact: ArtifactWrite,
    summary_md: str,
    reviewer_id: str,
) -> str:
    summary_line = summary_md.strip().splitlines()[0]
    return (
        f"@{reviewer_id} Please review {run.id} for {run.task_id}.\n\n"
        f"Result: {artifact.relative_path}\n\n"
        f"Summary: {summary_line}"
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()
