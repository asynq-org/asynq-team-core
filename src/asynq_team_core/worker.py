"""Local worker loop primitives."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.agent_manifests import (
    AgentManifest,
    list_agent_manifests,
    load_agent_manifest,
)
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization
from asynq_team_core.run_submission import RunSubmission, submit_authorized_run_for_review
from asynq_team_core.run_task import StartedTaskRun, start_authorized_task_run
from asynq_team_core.runner_adapter import execute_run_adapter_command
from asynq_team_core.runner_execution import RunnerExecution
from asynq_team_core.runs import RunStatus, update_run_status
from asynq_team_core.tasks import (
    Task,
    TaskStatus,
    get_next_agent_task,
    get_next_unassigned_task,
    update_task_assignee,
    update_task_status,
)

ROUTER_AGENT_ID = "ea"


@dataclass(frozen=True)
class RoutedTask:
    """Result of assigning one unassigned task to an agent."""

    task: Task
    assignee_id: str
    reason: str


@dataclass(frozen=True)
class WorkerRunOnceResult:
    """Result of one local worker scheduling pass."""

    task: Task | None
    authorization: CapabilityAuthorization | None
    started: StartedTaskRun | None
    routed: RoutedTask | None = None
    execution: RunnerExecution | None = None
    submission: RunSubmission | None = None


@dataclass(frozen=True)
class _RunnerWorkerResult:
    authorization: CapabilityAuthorization | None
    execution: RunnerExecution | None
    submission: RunSubmission | None


def run_worker_once(
    database_path: Path,
    layout: ProjectLayout,
    agent_id: str,
    actor_type: str = "agent",
    actor_id: str | None = None,
    approver_id: str = "founder",
    requested_model: str | None = None,
    execute_runner: bool = False,
    runner_timeout_seconds: int = 300,
    clock: Clock = utc_now,
) -> WorkerRunOnceResult:
    """Claim the next task for an agent and optionally execute its runner."""
    effective_actor_id = actor_id or agent_id
    if agent_id == ROUTER_AGENT_ID:
        routed = route_next_unassigned_task(
            database_path=database_path,
            layout=layout,
            actor_type=actor_type,
            actor_id=effective_actor_id,
            clock=clock,
        )
        if routed is not None:
            return WorkerRunOnceResult(
                task=routed.task,
                authorization=None,
                started=None,
                routed=routed,
            )

    with connect_database(database_path) as connection:
        task = get_next_agent_task(connection, agent_id)

    if task is None:
        return WorkerRunOnceResult(task=None, authorization=None, started=None)

    result = start_authorized_task_run(
        database_path=database_path,
        layout=layout,
        task_id=task.id,
        agent_id=agent_id,
        actor_type=actor_type,
        actor_id=effective_actor_id,
        approver_id=approver_id,
        requested_model=requested_model,
        clock=clock,
    )
    if result.started is None:
        return WorkerRunOnceResult(
            task=task,
            authorization=result.authorization,
            started=None,
        )

    with connect_database(database_path) as connection:
        updated_task = update_task_status(
            connection,
            task_id=task.id,
            status=TaskStatus.IN_PROGRESS,
            actor_type=actor_type,
            actor_id=effective_actor_id,
            clock=clock,
        )

    runner_result = _execute_runner_if_requested(
        database_path=database_path,
        layout=layout,
        started=result.started,
        task=updated_task,
        actor_type=actor_type,
        actor_id=effective_actor_id,
        approver_id=approver_id,
        runner_timeout_seconds=runner_timeout_seconds,
        execute_runner=execute_runner,
        clock=clock,
    )

    return WorkerRunOnceResult(
        task=updated_task,
        authorization=runner_result.authorization or result.authorization,
        started=result.started,
        execution=runner_result.execution,
        submission=runner_result.submission,
    )


def _execute_runner_if_requested(
    database_path: Path,
    layout: ProjectLayout,
    started: StartedTaskRun,
    task: Task,
    actor_type: str,
    actor_id: str,
    approver_id: str,
    runner_timeout_seconds: int,
    execute_runner: bool,
    clock: Clock,
) -> _RunnerWorkerResult:
    if not execute_runner:
        return _RunnerWorkerResult(authorization=None, execution=None, submission=None)

    execution = execute_run_adapter_command(
        database_path=database_path,
        layout=layout,
        run=started.work_packet.run,
        work_packet_path=started.work_packet.artifact.relative_path,
        actor_type=actor_type,
        actor_id=actor_id,
        timeout_seconds=runner_timeout_seconds,
    )
    if execution.exit_code != 0:
        with connect_database(database_path) as connection:
            update_run_status(
                connection,
                run_id=started.work_packet.run.id,
                status=RunStatus.FAILED,
                actor_type=actor_type,
                actor_id=actor_id,
                clock=clock,
            )
            update_task_status(
                connection,
                task_id=task.id,
                status=TaskStatus.BLOCKED,
                actor_type=actor_type,
                actor_id=actor_id,
                clock=clock,
            )

        return _RunnerWorkerResult(
            authorization=None,
            execution=execution,
            submission=None,
        )

    submitted = submit_authorized_run_for_review(
        database_path=database_path,
        layout=layout,
        run_id=started.work_packet.run.id,
        summary_md="Runner completed successfully.",
        checks_md=_render_runner_checks(execution),
        reviewer_id=_reviewer_id_for_run(layout, started.work_packet.run.agent_id),
        actor_type=actor_type,
        actor_id=actor_id,
        approver_id=approver_id,
        clock=clock,
    )

    return _RunnerWorkerResult(
        authorization=submitted.authorization,
        execution=execution,
        submission=submitted.submission,
    )


def _render_runner_checks(execution: RunnerExecution) -> str:
    sections = [
        f"- Runner command: `{shlex.join(execution.command)}`",
        f"- Exit code: {execution.exit_code}",
        f"- Timed out: {_format_bool(execution.timed_out)}",
        f"- Duration ms: {execution.duration_ms}",
    ]
    if execution.stdout.strip():
        sections.extend(("", "### Stdout", "```text", execution.stdout.rstrip(), "```"))
    if execution.stderr.strip():
        sections.extend(("", "### Stderr", "```text", execution.stderr.rstrip(), "```"))

    return "\n".join(sections)


def _reviewer_id_for_run(layout: ProjectLayout, agent_id: str) -> str:
    try:
        manifest = load_agent_manifest(layout, agent_id)
    except ValueError:
        return "founder"
    return manifest.supervisor or "founder"


def _format_bool(value: bool) -> str:
    return "yes" if value else "no"


def route_next_unassigned_task(
    database_path: Path,
    layout: ProjectLayout,
    actor_type: str = "agent",
    actor_id: str = ROUTER_AGENT_ID,
    clock: Clock = utc_now,
) -> RoutedTask | None:
    """Assign the oldest unassigned task to the most appropriate configured agent."""
    with connect_database(database_path) as connection:
        task = get_next_unassigned_task(connection)

    if task is None:
        return None

    manifests = list_agent_manifests(layout)
    assignee = _select_task_assignee(task, manifests)
    with connect_database(database_path) as connection:
        updated_task = update_task_assignee(
            connection,
            task_id=task.id,
            assignee_id=assignee.id,
            actor_type=actor_type,
            actor_id=actor_id,
            clock=clock,
        )

    return RoutedTask(
        task=updated_task,
        assignee_id=assignee.id,
        reason=f"Matched task to {assignee.role} agent {assignee.id}.",
    )


def _select_task_assignee(task: Task, manifests: tuple[AgentManifest, ...]) -> AgentManifest:
    if not manifests:
        raise ValueError("No agent manifests are configured.")

    target_role = _target_role_for_task(task)
    return (
        _find_agent_by_role(manifests, target_role)
        or _find_agent_by_role(manifests, "engineer")
        or _find_agent_by_role(manifests, "ea")
        or manifests[0]
    )


def _target_role_for_task(task: Task) -> str:
    text = task.title.lower()
    if _contains_any(text, ("review", "audit", "approve", "approval", "policy", "risk")):
        return "supervisor"
    if _contains_any(text, ("inbox", "triage", "summary", "summarize", "follow-up", "follow up")):
        return "ea"
    return "engineer"


def _find_agent_by_role(
    manifests: tuple[AgentManifest, ...],
    role: str,
) -> AgentManifest | None:
    for manifest in manifests:
        if manifest.role == role:
            return manifest
    return None


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
