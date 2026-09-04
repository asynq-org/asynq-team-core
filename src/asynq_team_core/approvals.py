"""Approval records for gated runtime actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from asynq_team_core.database import (
    DatabaseConnection,
    DatabaseRow,
    get_next_sequential_id,
    insert_event,
)
from asynq_team_core.events import Clock, create_event, format_event_time, utc_now
from asynq_team_core.inbox import (
    InboxItem,
    InboxItemType,
    complete_inbox_items_for_source,
    create_inbox_item,
)


class ApprovalStatus(str, Enum):
    """Supported approval statuses."""

    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"


@dataclass(frozen=True)
class Approval:
    """A structured approval request for a gated action."""

    id: str
    action: str
    reason: str
    requester_type: str
    requester_id: str
    approver_id: str
    subject_type: str | None
    subject_id: str | None
    status: ApprovalStatus
    requested_at: str
    decided_at: str | None
    decided_by_type: str | None
    decided_by_id: str | None
    decision_reason: str | None


@dataclass(frozen=True)
class ApprovalRequest:
    """Result of requesting approval."""

    approval: Approval
    inbox_item: InboxItem


@dataclass(frozen=True)
class ApprovalDecision:
    """Result of deciding an approval."""

    approval: Approval
    completed_inbox_items: tuple[InboxItem, ...]


def request_approval(
    connection: DatabaseConnection,
    action: str,
    reason: str,
    requester_type: str,
    requester_id: str,
    approver_id: str = "founder",
    subject_type: str | None = None,
    subject_id: str | None = None,
    clock: Clock = utc_now,
) -> ApprovalRequest:
    """Create a pending approval and a matching inbox item."""
    requested_at = format_event_time(clock())
    approval_id = get_next_sequential_id(connection, "approvals", "APR")
    approval = Approval(
        id=approval_id,
        action=_require_non_empty(action, "action"),
        reason=_require_non_empty(reason, "reason"),
        requester_type=_require_non_empty(requester_type, "requester_type"),
        requester_id=_require_non_empty(requester_id, "requester_id"),
        approver_id=_require_non_empty(approver_id, "approver_id"),
        subject_type=subject_type,
        subject_id=subject_id,
        status=ApprovalStatus.PENDING,
        requested_at=requested_at,
        decided_at=None,
        decided_by_type=None,
        decided_by_id=None,
        decision_reason=None,
    )

    connection.execute(
        """
        insert into approvals (
            id,
            action,
            reason,
            requester_type,
            requester_id,
            approver_id,
            subject_type,
            subject_id,
            status,
            requested_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval.id,
            approval.action,
            approval.reason,
            approval.requester_type,
            approval.requester_id,
            approval.approver_id,
            approval.subject_type,
            approval.subject_id,
            approval.status.value,
            approval.requested_at,
        ),
    )
    insert_event(
        connection,
        create_event(
            event_type="approval.requested",
            entity_type="approval",
            entity_id=approval.id,
            actor_type=approval.requester_type,
            actor_id=approval.requester_id,
            payload={
                "action": approval.action,
                "reason": approval.reason,
                "approver_id": approval.approver_id,
                "subject_type": approval.subject_type,
                "subject_id": approval.subject_id,
            },
            clock=lambda: _parse_event_time(requested_at),
        ),
    )
    inbox_item = create_inbox_item(
        connection,
        recipient_id=approval.approver_id,
        item_type=InboxItemType.APPROVAL,
        title=f"Approval required: {approval.action}",
        body=approval.reason,
        actor_type=approval.requester_type,
        actor_id=approval.requester_id,
        source_type="approval",
        source_id=approval.id,
        clock=lambda: _parse_event_time(requested_at),
    )

    return ApprovalRequest(approval=approval, inbox_item=inbox_item)


def get_approval(connection: DatabaseConnection, approval_id: str) -> Approval | None:
    """Return an approval by id."""
    row = connection.execute("select * from approvals where id = ?", (approval_id,)).fetchone()
    if row is None:
        return None
    return _approval_from_row(row)


def list_approvals(
    connection: DatabaseConnection,
    status: ApprovalStatus | None = ApprovalStatus.PENDING,
    approver_id: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """Return approvals ordered by newest request first."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")

    clauses: list[str] = []
    params: list[str | int] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)
    if approver_id is not None:
        clauses.append("approver_id = ?")
        params.append(_require_non_empty(approver_id, "approver_id"))

    where = f" where {' and '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = connection.execute(
        f"select * from approvals{where} order by requested_at desc, id desc limit ?",
        tuple(params),
    ).fetchall()

    return [_approval_from_row(row) for row in rows]


def find_matching_approval(
    connection: DatabaseConnection,
    action: str,
    requester_type: str,
    requester_id: str,
    status: ApprovalStatus,
    subject_type: str | None = None,
    subject_id: str | None = None,
) -> Approval | None:
    """Return the newest approval matching an action, requester, subject, and status."""
    clean_action = _require_non_empty(action, "action")
    clean_requester_type = _require_non_empty(requester_type, "requester_type")
    clean_requester_id = _require_non_empty(requester_id, "requester_id")

    subject_clauses: list[str] = []
    subject_params: list[str] = []
    if subject_type is None:
        subject_clauses.append("subject_type is null")
    else:
        subject_clauses.append("subject_type = ?")
        subject_params.append(_require_non_empty(subject_type, "subject_type"))
    if subject_id is None:
        subject_clauses.append("subject_id is null")
    else:
        subject_clauses.append("subject_id = ?")
        subject_params.append(_require_non_empty(subject_id, "subject_id"))
    subject_clause = " and ".join(subject_clauses)

    row = connection.execute(
        f"""
        select * from approvals
        where action = ?
        and requester_type = ?
        and requester_id = ?
        and status = ?
        and {subject_clause}
        order by requested_at desc, id desc
        limit 1
        """,
        (clean_action, clean_requester_type, clean_requester_id, status.value, *subject_params),
    ).fetchone()
    if row is None:
        return None
    return _approval_from_row(row)


def grant_approval(
    connection: DatabaseConnection,
    approval_id: str,
    actor_type: str,
    actor_id: str,
    reason: str | None = None,
    clock: Clock = utc_now,
) -> ApprovalDecision:
    """Grant a pending approval."""
    return _decide_approval(
        connection,
        approval_id=approval_id,
        status=ApprovalStatus.GRANTED,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        clock=clock,
    )


def deny_approval(
    connection: DatabaseConnection,
    approval_id: str,
    actor_type: str,
    actor_id: str,
    reason: str | None = None,
    clock: Clock = utc_now,
) -> ApprovalDecision:
    """Deny a pending approval."""
    return _decide_approval(
        connection,
        approval_id=approval_id,
        status=ApprovalStatus.DENIED,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        clock=clock,
    )


def _decide_approval(
    connection: DatabaseConnection,
    approval_id: str,
    status: ApprovalStatus,
    actor_type: str,
    actor_id: str,
    reason: str | None,
    clock: Clock,
) -> ApprovalDecision:
    approval = get_approval(connection, approval_id)
    if approval is None:
        raise ValueError(f"Approval not found: {approval_id}")
    if approval.status is not ApprovalStatus.PENDING:
        raise ValueError(f"Approval is already decided: {approval_id}")

    decided_at = format_event_time(clock())
    clean_actor_type = _require_non_empty(actor_type, "actor_type")
    clean_actor_id = _require_non_empty(actor_id, "actor_id")
    connection.execute(
        """
        update approvals
        set status = ?,
            decided_at = ?,
            decided_by_type = ?,
            decided_by_id = ?,
            decision_reason = ?
        where id = ?
        """,
        (
            status.value,
            decided_at,
            clean_actor_type,
            clean_actor_id,
            reason,
            approval.id,
        ),
    )
    insert_event(
        connection,
        create_event(
            event_type=f"approval.{status.value}",
            entity_type="approval",
            entity_id=approval.id,
            actor_type=clean_actor_type,
            actor_id=clean_actor_id,
            payload={
                "action": approval.action,
                "previous_status": approval.status.value,
                "decision_reason": reason,
            },
            clock=lambda: _parse_event_time(decided_at),
        ),
    )
    completed_items = complete_inbox_items_for_source(
        connection,
        source_type="approval",
        source_id=approval.id,
        actor_type=clean_actor_type,
        actor_id=clean_actor_id,
        clock=lambda: _parse_event_time(decided_at),
    )

    decided = get_approval(connection, approval.id)
    if decided is None:
        raise RuntimeError(f"Approval disappeared after decision: {approval.id}")
    return ApprovalDecision(approval=decided, completed_inbox_items=completed_items)


def _approval_from_row(row: DatabaseRow) -> Approval:
    return Approval(
        id=row["id"],
        action=row["action"],
        reason=row["reason"],
        requester_type=row["requester_type"],
        requester_id=row["requester_id"],
        approver_id=row["approver_id"],
        subject_type=row["subject_type"],
        subject_id=row["subject_id"],
        status=ApprovalStatus(row["status"]),
        requested_at=row["requested_at"],
        decided_at=row["decided_at"],
        decided_by_type=row["decided_by_type"],
        decided_by_id=row["decided_by_id"],
        decision_reason=row["decision_reason"],
    )


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
