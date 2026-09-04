"""Task run start workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.artifact_policy import authorize_task_run_artifact_creation
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization
from asynq_team_core.run_service import CreatedRun, create_run_with_artifact_dir
from asynq_team_core.run_work import RunWorkPacket, prepare_run_work_packet
from asynq_team_core.tasks import get_task


@dataclass(frozen=True)
class StartedTaskRun:
    """Result of creating a run and preparing its work packet."""

    created: CreatedRun
    work_packet: RunWorkPacket


@dataclass(frozen=True)
class AuthorizedStartedTaskRun:
    """Result of an authorized task run start attempt."""

    authorization: CapabilityAuthorization | None
    started: StartedTaskRun | None


def start_task_run(
    database_path: Path,
    layout: ProjectLayout,
    task_id: str,
    agent_id: str,
    actor_type: str,
    actor_id: str,
    clock: Clock = utc_now,
) -> StartedTaskRun:
    """Create an agent run for a task and prepare its local work packet."""
    created = create_run_with_artifact_dir(
        database_path=database_path,
        layout=layout,
        task_id=task_id,
        agent_id=agent_id,
        actor_type=actor_type,
        actor_id=actor_id,
        clock=clock,
    )
    work_packet = prepare_run_work_packet(
        database_path=database_path,
        layout=layout,
        run_id=created.run.id,
        actor_type=actor_type,
        actor_id=actor_id,
        clock=clock,
    )

    return StartedTaskRun(created=created, work_packet=work_packet)


def start_authorized_task_run(
    database_path: Path,
    layout: ProjectLayout,
    task_id: str,
    agent_id: str,
    actor_type: str,
    actor_id: str,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> AuthorizedStartedTaskRun:
    """Create a task run after enforcing agent artifact.create capability."""
    _require_existing_task(database_path, task_id)
    authorization = authorize_task_run_artifact_creation(
        database_path=database_path,
        layout=layout,
        task_id=task_id,
        actor_type=actor_type,
        actor_id=actor_id,
        approver_id=approver_id,
        clock=clock,
    )
    if authorization is not None and authorization.approval_request is not None:
        return AuthorizedStartedTaskRun(authorization=authorization, started=None)

    started = start_task_run(
        database_path=database_path,
        layout=layout,
        task_id=task_id,
        agent_id=agent_id,
        actor_type=actor_type,
        actor_id=actor_id,
        clock=clock,
    )

    return AuthorizedStartedTaskRun(authorization=authorization, started=started)


def _require_existing_task(database_path: Path, task_id: str) -> None:
    with connect_database(database_path) as connection:
        if get_task(connection, task_id) is None:
            raise ValueError(f"Task not found: {task_id}")
