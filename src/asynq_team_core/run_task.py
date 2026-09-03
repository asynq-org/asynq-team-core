"""Task run start workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.run_service import CreatedRun, create_run_with_artifact_dir
from asynq_team_core.run_work import RunWorkPacket, prepare_run_work_packet


@dataclass(frozen=True)
class StartedTaskRun:
    """Result of creating a run and preparing its work packet."""

    created: CreatedRun
    work_packet: RunWorkPacket


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
