from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.approvals import (
    ApprovalStatus,
    deny_approval,
    get_approval,
    grant_approval,
    list_approvals,
    request_approval,
)
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import InboxItemStatus, list_inbox_items


def test_request_approval_creates_pending_approval_and_inbox_item(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        requested = request_approval(
            connection,
            action="main.merge",
            reason="Merge reviewed changes.",
            requester_type="agent",
            requester_id="george",
            approver_id="founder",
            subject_type="task",
            subject_id="TASK-0001",
            clock=lambda: datetime(2026, 8, 24, 12, 30, 0, tzinfo=UTC),
        )
        loaded = get_approval(connection, requested.approval.id)
        inbox_items = list_inbox_items(connection, recipient_id="founder")
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("approval.requested", requested.approval.id),
        ).fetchone()

    assert requested.approval.id == "APR-0001"
    assert requested.approval.status is ApprovalStatus.PENDING
    assert loaded == requested.approval
    assert inbox_items == [requested.inbox_item]
    assert requested.inbox_item.source_id == requested.approval.id
    assert event is not None


def test_list_approvals_filters_by_status_and_approver(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        founder_request = request_approval(
            connection,
            action="main.merge",
            reason="Merge reviewed changes.",
            requester_type="agent",
            requester_id="george",
            approver_id="founder",
        )
        request_approval(
            connection,
            action="external.write",
            reason="Send update.",
            requester_type="agent",
            requester_id="ea",
            approver_id="supervisor",
        )

        approvals = list_approvals(connection, approver_id="founder")

    assert approvals == [founder_request.approval]


def test_grant_approval_updates_status_and_closes_inbox_item(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        requested = request_approval(
            connection,
            action="main.merge",
            reason="Merge reviewed changes.",
            requester_type="agent",
            requester_id="george",
        )
        decision = grant_approval(
            connection,
            requested.approval.id,
            actor_type="human",
            actor_id="founder",
            reason="Looks safe.",
        )
        open_items = list_inbox_items(connection)
        done_items = list_inbox_items(connection, status=InboxItemStatus.DONE)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("approval.granted", requested.approval.id),
        ).fetchone()

    assert decision.approval.status is ApprovalStatus.GRANTED
    assert decision.approval.decision_reason == "Looks safe."
    assert decision.completed_inbox_items == tuple(done_items)
    assert open_items == []
    assert done_items[0].source_id == requested.approval.id
    assert event is not None


def test_deny_approval_updates_status(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        requested = request_approval(
            connection,
            action="external.write",
            reason="Send update.",
            requester_type="agent",
            requester_id="ea",
        )
        decision = deny_approval(
            connection,
            requested.approval.id,
            actor_type="human",
            actor_id="founder",
        )

    assert decision.approval.status is ApprovalStatus.DENIED


def test_deciding_already_decided_approval_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        requested = request_approval(
            connection,
            action="main.merge",
            reason="Merge reviewed changes.",
            requester_type="agent",
            requester_id="george",
        )
        grant_approval(
            connection,
            requested.approval.id,
            actor_type="human",
            actor_id="founder",
        )

        with pytest.raises(ValueError, match="already decided"):
            deny_approval(
                connection,
                requested.approval.id,
                actor_type="human",
                actor_id="founder",
            )
