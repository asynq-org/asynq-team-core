"""Higher-level task workflows for core callers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.artifacts import ArtifactWrite, write_task_brief
from asynq_team_core.database import connect_database, get_next_sequential_id, insert_event
from asynq_team_core.events import Clock, create_event, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization, authorize_agent_capability
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


@dataclass(frozen=True)
class AuthorizedTaskCreation:
    """Result of an authorized task creation attempt."""

    authorization: CapabilityAuthorization | None
    created: CreatedTask | None


@dataclass(frozen=True)
class AuthorizedFollowUpTaskCreation:
    """Result of an authorized follow-up task creation attempt."""

    authorization: CapabilityAuthorization | None
    created: CreatedFollowUpTask | None


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


def create_authorized_task_with_brief(
    database_path: Path,
    layout: ProjectLayout,
    title: str,
    brief_md: str,
    actor_type: str,
    actor_id: str,
    priority: str = "normal",
    assignee_id: str | None = None,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> AuthorizedTaskCreation:
    """Create a task after enforcing agent task.create capability."""
    authorization = _authorize_agent_task_creation(
        database_path=database_path,
        layout=layout,
        title=title,
        actor_type=actor_type,
        actor_id=actor_id,
        approver_id=approver_id,
        subject_id=None,
        clock=clock,
    )
    if authorization is not None and authorization.approval_request is not None:
        return AuthorizedTaskCreation(authorization=authorization, created=None)

    created = create_task_with_brief(
        database_path=database_path,
        layout=layout,
        title=title,
        brief_md=brief_md,
        actor_type=actor_type,
        actor_id=actor_id,
        priority=priority,
        assignee_id=assignee_id,
        clock=clock,
    )

    return AuthorizedTaskCreation(authorization=authorization, created=created)


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


def create_authorized_follow_up_task(
    database_path: Path,
    layout: ProjectLayout,
    parent_task_id: str,
    title: str,
    brief_md: str,
    actor_type: str,
    actor_id: str,
    priority: str = "normal",
    assignee_id: str | None = None,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> AuthorizedFollowUpTaskCreation:
    """Create a follow-up task after enforcing agent task.create capability."""
    _require_parent_task(database_path, parent_task_id)
    authorization = _authorize_agent_task_creation(
        database_path=database_path,
        layout=layout,
        title=title,
        actor_type=actor_type,
        actor_id=actor_id,
        approver_id=approver_id,
        subject_id=parent_task_id,
        clock=clock,
    )
    if authorization is not None and authorization.approval_request is not None:
        return AuthorizedFollowUpTaskCreation(authorization=authorization, created=None)

    created = create_follow_up_task(
        database_path=database_path,
        layout=layout,
        parent_task_id=parent_task_id,
        title=title,
        brief_md=brief_md,
        actor_type=actor_type,
        actor_id=actor_id,
        priority=priority,
        assignee_id=assignee_id,
        clock=clock,
    )

    return AuthorizedFollowUpTaskCreation(authorization=authorization, created=created)


def _authorize_agent_task_creation(
    database_path: Path,
    layout: ProjectLayout,
    title: str,
    actor_type: str,
    actor_id: str,
    approver_id: str,
    subject_id: str | None,
    clock: Clock,
) -> CapabilityAuthorization | None:
    if actor_type != "agent":
        return None

    return authorize_agent_capability(
        database_path=database_path,
        layout=layout,
        agent_id=actor_id,
        capability="task.create",
        reason=f"Create task: {title}",
        approver_id=approver_id,
        subject_type="task",
        subject_id=subject_id,
        clock=clock,
    )


def _require_parent_task(database_path: Path, parent_task_id: str) -> Task:
    with connect_database(database_path) as connection:
        parent_task = get_task(connection, parent_task_id)
        if parent_task is None:
            raise ValueError(f"Parent task not found: {parent_task_id}")

    return parent_task
