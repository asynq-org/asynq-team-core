"""Higher-level run workflows for core callers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.database import connect_database, get_next_sequential_id
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runs import Run, create_run


@dataclass(frozen=True)
class CreatedRun:
    """Result of creating a run and its artifact directory."""

    run: Run
    artifact_dir: Path


def create_run_with_artifact_dir(
    database_path: Path,
    layout: ProjectLayout,
    task_id: str,
    agent_id: str,
    actor_type: str,
    actor_id: str,
    clock: Clock = utc_now,
) -> CreatedRun:
    """Create a run record and a project-local artifact directory."""
    with connect_database(database_path) as connection:
        run_id = get_next_sequential_id(connection, "runs", "RUN")
        artifact_dir = layout.runs_dir / agent_id / run_id
        _ensure_child_path(layout.runs_dir, artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=False)
        run = create_run(
            connection,
            task_id=task_id,
            agent_id=agent_id,
            actor_type=actor_type,
            actor_id=actor_id,
            run_id=run_id,
            artifact_dir_path=artifact_dir.relative_to(layout.workspace).as_posix(),
            clock=clock,
        )

    return CreatedRun(run=run, artifact_dir=artifact_dir)


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Run artifact path escapes parent directory: {child}") from exc
