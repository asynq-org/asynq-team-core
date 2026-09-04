"""Local worker loop primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization
from asynq_team_core.run_task import StartedTaskRun, start_authorized_task_run
from asynq_team_core.tasks import Task, TaskStatus, get_next_agent_task, update_task_status


@dataclass(frozen=True)
class WorkerRunOnceResult:
    """Result of one local worker scheduling pass."""

    task: Task | None
    authorization: CapabilityAuthorization | None
    started: StartedTaskRun | None


def run_worker_once(
    database_path: Path,
    layout: ProjectLayout,
    agent_id: str,
    actor_type: str = "agent",
    actor_id: str | None = None,
    approver_id: str = "founder",
    requested_model: str | None = None,
    clock: Clock = utc_now,
) -> WorkerRunOnceResult:
    """Claim the next task for an agent and prepare its run work packet."""
    effective_actor_id = actor_id or agent_id
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

    return WorkerRunOnceResult(
        task=updated_task,
        authorization=result.authorization,
        started=result.started,
    )
