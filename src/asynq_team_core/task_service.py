"""Higher-level task workflows for core callers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.artifacts import ArtifactWrite, write_task_brief
from asynq_team_core.database import connect_database, get_next_sequential_id
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.tasks import Task, create_task


@dataclass(frozen=True)
class CreatedTask:
    """Result of creating a task and its initial artifacts."""

    task: Task
    brief: ArtifactWrite


def create_task_with_brief(
    database_path: Path,
    layout: ProjectLayout,
    title: str,
    brief_md: str,
    actor_type: str,
    actor_id: str,
    priority: str = "normal",
    assignee_id: str | None = None,
    clock: Clock = utc_now,
) -> CreatedTask:
    """Create a task, write its brief artifact, and record an audit event."""
    with connect_database(database_path) as connection:
        task_id = get_next_sequential_id(connection, "tasks", "TASK")
        brief = write_task_brief(layout, task_id, brief_md)
        task = create_task(
            connection,
            title=title,
            actor_type=actor_type,
            actor_id=actor_id,
            priority=priority,
            assignee_id=assignee_id,
            brief_artifact_path=brief.relative_path,
            task_id=task_id,
            clock=clock,
        )

    return CreatedTask(task=task, brief=brief)
