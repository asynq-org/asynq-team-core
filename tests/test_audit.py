from pathlib import Path

import pytest

from asynq_team_core.audit import list_task_audit_events
from asynq_team_core.comments import create_task_comment
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.runs import RunStatus, update_run_status
from asynq_team_core.task_service import create_task_with_brief


def test_list_task_audit_events_includes_task_run_and_comment_events(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    task = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    ).task
    run = create_run_with_artifact_dir(
        database_path=layout.database_path,
        layout=layout,
        task_id=task.id,
        agent_id="george",
        actor_type="human",
        actor_id="founder",
    ).run
    with connect_database(layout.database_path) as connection:
        update_run_status(
            connection,
            run_id=run.id,
            status=RunStatus.WORKING,
            actor_type="agent",
            actor_id="george",
        )
        create_task_comment(
            connection,
            task_id=task.id,
            body="@supervisor Please review.",
            author_type="agent",
            author_id="george",
            mentions=("supervisor",),
        )

    events = list_task_audit_events(layout.database_path, task.id)

    event_types = [event.event_type for event in events]
    assert "task.created" in event_types
    assert "run.created" in event_types
    assert "run.status_changed" in event_types
    assert "comment.created" in event_types
    assert "comment.mentioned" in event_types


def test_list_task_audit_events_rejects_missing_task(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    with pytest.raises(ValueError, match="Task not found: TASK-9999"):
        list_task_audit_events(layout.database_path, "TASK-9999")
