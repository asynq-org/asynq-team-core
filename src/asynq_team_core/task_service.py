"""Higher-level task workflows for core callers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.artifacts import ArtifactWrite, write_task_brief
from asynq_team_core.database import connect_database, get_next_sequential_id, insert_event
from asynq_team_core.events import Clock, create_event, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.tasks import Task, create_task, get_task


@dataclass(frozen=True)
class CreatedTask:
    """Result of creating a task and its initial artifacts."""

    task: Task
    brief: ArtifactWrite


@dataclass(frozen=True)
class CreatedFollowUpTask:
    """Result of creating a follow-up task and its brief."""

    parent_task: Task
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


def create_follow_up_task(
    database_path: Path,
    layout: ProjectLayout,
    parent_task_id: str,
    title: str,
    brief_md: str,
    actor_type: str,
    actor_id: str,
    priority: str = "normal",
    assignee_id: str | None = None,
    clock: Clock = utc_now,
) -> CreatedFollowUpTask:
    """Create a follow-up task linked to an existing parent task."""
    with connect_database(database_path) as connection:
        parent_task = get_task(connection, parent_task_id)
        if parent_task is None:
            raise ValueError(f"Parent task not found: {parent_task_id}")

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
            parent_task_id=parent_task.id,
            task_id=task_id,
            clock=clock,
        )
        insert_event(
            connection,
            create_event(
                event_type="task.followup_created",
                entity_type="task",
                entity_id=parent_task.id,
                actor_type=actor_type,
                actor_id=actor_id,
                payload={
                    "follow_up_task_id": task.id,
                    "title": task.title,
                    "brief_artifact_path": brief.relative_path,
                },
                clock=clock,
            ),
        )

    return CreatedFollowUpTask(parent_task=parent_task, task=task, brief=brief)
