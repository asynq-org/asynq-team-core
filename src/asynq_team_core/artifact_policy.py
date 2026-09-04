"""Capability checks for project artifact writes."""

from __future__ import annotations

from pathlib import Path

from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization, authorize_agent_capability
from asynq_team_core.runs import Run


def authorize_run_artifact_creation(
    database_path: Path,
    layout: ProjectLayout,
    run: Run,
    actor_type: str,
    actor_id: str,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> CapabilityAuthorization | None:
    """Authorize an actor before it writes an artifact for an existing run."""
    if actor_type != "agent":
        return None

    return authorize_agent_capability(
        database_path=database_path,
        layout=layout,
        agent_id=actor_id,
        capability="artifact.create",
        reason=f"Create artifact for run: {run.id}",
        approver_id=approver_id,
        subject_type="run",
        subject_id=run.id,
        clock=clock,
    )


def authorize_task_run_artifact_creation(
    database_path: Path,
    layout: ProjectLayout,
    task_id: str,
    actor_type: str,
    actor_id: str,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> CapabilityAuthorization | None:
    """Authorize an actor before it creates the first artifact for a new task run."""
    if actor_type != "agent":
        return None

    return authorize_agent_capability(
        database_path=database_path,
        layout=layout,
        agent_id=actor_id,
        capability="artifact.create",
        reason=f"Create run artifacts for task: {task_id}",
        approver_id=approver_id,
        subject_type="task",
        subject_id=task_id,
        clock=clock,
    )
