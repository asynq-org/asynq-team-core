from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.comments import (
    CommentMentionStatus,
    authorize_task_comment_creation,
    create_authorized_task_comment,
    create_task_comment,
    get_comment,
    list_comment_mentions,
    list_task_comments,
)
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemType, list_inbox_items
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.policy import CapabilityDecision
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.tasks import create_task


def test_create_task_comment_persists_comment_mentions_and_inbox_items(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        created = create_task_comment(
            connection,
            task_id=task.id,
            body="@supervisor Please review the plan.",
            author_type="agent",
            author_id="george",
            mentions=("supervisor", "supervisor"),
            clock=lambda: datetime(2026, 9, 2, 12, 30, 0, tzinfo=UTC),
        )
        loaded = get_comment(connection, created.comment.id)
        mentions = list_comment_mentions(connection, recipient_id="supervisor")
        inbox_items = list_inbox_items(connection, recipient_id="supervisor")
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("comment.created", created.comment.id),
        ).fetchone()

    assert created.comment.id == "CMT-0001"
    assert created.mentions[0].id == "MNT-0001"
    assert len(created.mentions) == 1
    assert loaded == created.comment
    assert mentions == list(created.mentions)
    assert inbox_items == list(created.inbox_items)
    assert inbox_items[0].item_type is InboxItemType.MENTION
    assert inbox_items[0].source_id == created.comment.id
    assert event is not None


def test_list_task_comments_returns_oldest_first(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        first = create_task_comment(
            connection,
            task_id=task.id,
            body="First comment.",
            author_type="human",
            author_id="founder",
            clock=lambda: datetime(2026, 9, 2, 12, 30, 0, tzinfo=UTC),
        )
        second = create_task_comment(
            connection,
            task_id=task.id,
            body="Second comment.",
            author_type="agent",
            author_id="george",
            clock=lambda: datetime(2026, 9, 2, 12, 31, 0, tzinfo=UTC),
        )

        comments = list_task_comments(connection, task.id)

    assert comments == [first.comment, second.comment]


def test_create_task_comment_rejects_missing_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="Task not found: TASK-9999"),
    ):
        create_task_comment(
            connection,
            task_id="TASK-9999",
            body="Missing task.",
            author_type="human",
            author_id="founder",
        )


def test_create_task_comment_rejects_empty_mention(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )

        with pytest.raises(ValueError, match="mention"):
            create_task_comment(
                connection,
                task_id=task.id,
                body="Invalid mention.",
                author_type="human",
                author_id="founder",
                mentions=("",),
            )


def test_list_comment_mentions_can_include_done_statuses(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        create_task_comment(
            connection,
            task_id=task.id,
            body="@supervisor Please review.",
            author_type="agent",
            author_id="george",
            mentions=("supervisor",),
        )

        mentions = list_comment_mentions(connection, status=CommentMentionStatus.OPEN)
        all_mentions = list_comment_mentions(connection, status=None)

    assert mentions == all_mentions


def test_create_authorized_task_comment_allows_agent_comment(tmp_path: Path) -> None:
    layout, task_id = _create_policy_workspace_with_task(tmp_path)

    result = create_authorized_task_comment(
        database_path=layout.database_path,
        layout=layout,
        task_id=task_id,
        body="Please review.",
        author_type="agent",
        author_id="george",
        mentions=("supervisor",),
    )

    assert result.authorization is not None
    assert result.authorization.evaluation.decision is CapabilityDecision.ALLOW
    assert result.created is not None
    assert result.created.comment.id == "CMT-0001"
    assert len(result.created.mentions) == 1


def test_authorize_task_comment_creation_does_not_create_comment(tmp_path: Path) -> None:
    layout, task_id = _create_policy_workspace_with_task(tmp_path)

    authorization = authorize_task_comment_creation(
        database_path=layout.database_path,
        layout=layout,
        task_id=task_id,
        author_type="agent",
        author_id="george",
    )

    assert authorization is not None
    assert authorization.evaluation.decision is CapabilityDecision.ALLOW
    with connect_database(layout.database_path) as connection:
        assert list_task_comments(connection, task_id) == []


def test_create_authorized_task_comment_requests_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout, task_id = _create_policy_workspace_with_task(tmp_path)
    _replace_engineer_comment_create_policy(layout, "require_approval")

    result = create_authorized_task_comment(
        database_path=layout.database_path,
        layout=layout,
        task_id=task_id,
        body="Please review.",
        author_type="agent",
        author_id="george",
        mentions=("supervisor",),
    )

    assert result.authorization is not None
    assert result.authorization.evaluation.decision is CapabilityDecision.REQUIRE_APPROVAL
    assert result.authorization.approval_request is not None
    assert result.authorization.approval_request.approval.subject_id == task_id
    assert result.created is None

    with connect_database(layout.database_path) as connection:
        assert list_task_comments(connection, task_id) == []
        assert list_comment_mentions(connection) == []
        approvals = list_approvals(connection)

    assert approvals == [result.authorization.approval_request.approval]


def test_create_authorized_task_comment_rejects_denied_agent(tmp_path: Path) -> None:
    layout, task_id = _create_policy_workspace_with_task(tmp_path)
    _replace_engineer_comment_create_policy(layout, "deny")

    with pytest.raises(PermissionError, match="denied for role"):
        create_authorized_task_comment(
            database_path=layout.database_path,
            layout=layout,
            task_id=task_id,
            body="Please review.",
            author_type="agent",
            author_id="george",
        )


def test_create_authorized_task_comment_bypasses_policy_for_humans(tmp_path: Path) -> None:
    layout, task_id = _create_workspace_with_task(tmp_path)

    result = create_authorized_task_comment(
        database_path=layout.database_path,
        layout=layout,
        task_id=task_id,
        body="Please review.",
        author_type="human",
        author_id="founder",
    )

    assert result.authorization is None
    assert result.created is not None
    assert result.created.comment.id == "CMT-0001"


def _create_workspace_with_task(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    initialize_database(layout.database_path)
    with connect_database(layout.database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )

    return layout, task.id


def _create_policy_workspace_with_task(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)
    with connect_database(layout.database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )

    return layout, task.id


def _replace_engineer_comment_create_policy(layout, target: str) -> None:
    path = layout.policy_dir / "capabilities.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    engineer = data["roles"]["engineer"]
    for field in ("allow", "require_approval", "deny"):
        engineer[field] = [item for item in engineer.get(field, []) if item != "comment.create"]
    engineer.setdefault(target, []).append("comment.create")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
