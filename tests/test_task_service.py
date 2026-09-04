from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.policy import CapabilityDecision
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.task_service import (
    create_authorized_follow_up_task,
    create_authorized_task_with_brief,
    create_follow_up_task,
    create_task_with_brief,
)
from asynq_team_core.tasks import get_task, list_follow_up_tasks, list_tasks


def test_create_task_with_brief_writes_artifact_and_task_record(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    created = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
        clock=lambda: datetime(2026, 8, 23, 12, 30, 0, tzinfo=UTC),
    )

    with connect_database(layout.database_path) as connection:
        loaded = get_task(connection, created.task.id)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("task.created", created.task.id),
        ).fetchone()

    assert created.task.id == "TASK-0001"
    assert created.task.brief_artifact_path == ".team/tasks/TASK-0001/brief.md"
    assert created.brief.path.read_text(encoding="utf-8") == "Build the first task.\n"
    assert loaded == created.task
    assert event["entity_id"] == "TASK-0001"


def test_create_task_with_brief_rolls_back_counter_when_artifact_fails(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    write_protected_task_dir = layout.tasks_dir / "TASK-0001"
    write_protected_task_dir.mkdir()
    (write_protected_task_dir / "brief.md").write_text("Existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_task_with_brief(
            database_path=layout.database_path,
            layout=layout,
            title="First task",
            brief_md="Replacement",
            actor_type="human",
            actor_id="founder",
        )

    write_protected_task_dir.rename(layout.tasks_dir / "TASK-FAILED")
    created = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    )

    assert created.task.id == "TASK-0001"


def test_create_follow_up_task_links_parent_and_writes_brief(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    parent = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Parent task",
        brief_md="Build the parent task.",
        actor_type="human",
        actor_id="founder",
    ).task

    created = create_follow_up_task(
        database_path=layout.database_path,
        layout=layout,
        parent_task_id=parent.id,
        title="Follow-up task",
        brief_md="Capture the follow-up.",
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        loaded = get_task(connection, created.task.id)
        follow_ups = list_follow_up_tasks(connection, parent.id)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("task.followup_created", parent.id),
        ).fetchone()

    assert created.parent_task == parent
    assert created.task.id == "TASK-0002"
    assert created.task.parent_task_id == parent.id
    assert created.brief.path.read_text(encoding="utf-8") == "Capture the follow-up.\n"
    assert loaded == created.task
    assert follow_ups == [created.task]
    assert event is not None


def test_create_follow_up_task_rejects_missing_parent(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    with pytest.raises(ValueError, match="Parent task not found: TASK-9999"):
        create_follow_up_task(
            database_path=layout.database_path,
            layout=layout,
            parent_task_id="TASK-9999",
            title="Follow-up task",
            brief_md="Capture the follow-up.",
            actor_type="agent",
            actor_id="george",
        )


def test_create_authorized_task_with_brief_allows_agent_task_creation(
    tmp_path: Path,
) -> None:
    layout = _create_initialized_policy_workspace(tmp_path)

    result = create_authorized_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Agent task",
        brief_md="Build the agent task.",
        actor_type="agent",
        actor_id="george",
    )

    assert result.authorization is not None
    assert result.authorization.evaluation.decision is CapabilityDecision.ALLOW
    assert result.created is not None
    assert result.created.task.id == "TASK-0001"


def test_create_authorized_task_with_brief_requests_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout = _create_initialized_policy_workspace(tmp_path)
    _replace_engineer_task_create_policy(layout, "require_approval")

    result = create_authorized_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Agent task",
        brief_md="Build the agent task.",
        actor_type="agent",
        actor_id="george",
    )

    assert result.authorization is not None
    assert result.authorization.evaluation.decision is CapabilityDecision.REQUIRE_APPROVAL
    assert result.authorization.approval_request is not None
    assert result.created is None
    with connect_database(layout.database_path) as connection:
        assert list_tasks(connection) == []
        approvals = list_approvals(connection)

    assert approvals == [result.authorization.approval_request.approval]


def test_create_authorized_task_with_brief_rejects_denied_agent(
    tmp_path: Path,
) -> None:
    layout = _create_initialized_policy_workspace(tmp_path)
    _replace_engineer_task_create_policy(layout, "deny")

    with pytest.raises(PermissionError, match="denied for role"):
        create_authorized_task_with_brief(
            database_path=layout.database_path,
            layout=layout,
            title="Agent task",
            brief_md="Build the agent task.",
            actor_type="agent",
            actor_id="george",
        )


def test_create_authorized_task_with_brief_bypasses_policy_for_humans(
    tmp_path: Path,
) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)

    result = create_authorized_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Human task",
        brief_md="Build the human task.",
        actor_type="human",
        actor_id="founder",
    )

    assert result.authorization is None
    assert result.created is not None
    assert result.created.task.id == "TASK-0001"


def test_create_authorized_follow_up_task_requests_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout = _create_initialized_policy_workspace(tmp_path)
    parent = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="Parent task",
        brief_md="Build the parent task.",
        actor_type="human",
        actor_id="founder",
    ).task
    _replace_engineer_task_create_policy(layout, "require_approval")

    result = create_authorized_follow_up_task(
        database_path=layout.database_path,
        layout=layout,
        parent_task_id=parent.id,
        title="Agent follow-up",
        brief_md="Build the follow-up.",
        actor_type="agent",
        actor_id="george",
    )

    assert result.authorization is not None
    assert result.authorization.approval_request is not None
    assert result.authorization.approval_request.approval.subject_id == parent.id
    assert result.created is None


def _create_initialized_policy_workspace(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)

    return layout


def _replace_engineer_task_create_policy(layout, target: str) -> None:
    path = layout.policy_dir / "capabilities.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    engineer = data["roles"]["engineer"]
    for field in ("allow", "require_approval", "deny"):
        engineer[field] = [item for item in engineer.get(field, []) if item != "task.create"]
    engineer.setdefault(target, []).append("task.create")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
