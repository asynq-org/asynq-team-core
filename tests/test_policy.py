from pathlib import Path

import pytest

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.inbox import list_inbox_items
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.policy import (
    CapabilityDecision,
    authorize_agent_capability,
    evaluate_agent_capability,
    load_capability_policy,
)
from asynq_team_core.project_files import seed_default_project_files


def test_load_capability_policy_reads_default_roles(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    policy = load_capability_policy(layout)

    assert policy.version == 1
    assert "engineer" in policy.roles
    assert "repo.read" in policy.roles["engineer"].allow
    assert "main.merge" in policy.roles["engineer"].require_approval
    assert "approval.bypass" in policy.roles["engineer"].deny
    assert "comment.create" in policy.roles["supervisor"].allow
    assert "artifact.create" in policy.roles["supervisor"].allow


def test_evaluate_agent_capability_allows_known_role_capability(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_agent_capability(layout, "george", "repo.read")

    assert evaluation.agent_id == "george"
    assert evaluation.role == "engineer"
    assert evaluation.capability == "repo.read"
    assert evaluation.decision is CapabilityDecision.ALLOW


def test_evaluate_agent_capability_requires_approval_for_gated_capability(
    tmp_path: Path,
) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_agent_capability(layout, "george", "main.merge")

    assert evaluation.decision is CapabilityDecision.REQUIRE_APPROVAL


def test_evaluate_agent_capability_denies_explicit_denial(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_agent_capability(layout, "supervisor", "repo.write")

    assert evaluation.decision is CapabilityDecision.DENY


def test_evaluate_agent_capability_denies_unlisted_capability(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_agent_capability(layout, "george", "unknown.action")

    assert evaluation.decision is CapabilityDecision.DENY
    assert "not listed" in evaluation.reason


def test_evaluate_agent_capability_rejects_missing_agent_manifest(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    with pytest.raises(ValueError, match="Agent manifest not found"):
        evaluate_agent_capability(layout, "missing", "repo.read")


def test_evaluate_agent_capability_rejects_agent_path_escape(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    with pytest.raises(ValueError, match="Policy path escapes parent directory"):
        evaluate_agent_capability(layout, "../policy/capabilities", "repo.read")


def test_authorize_agent_capability_allows_without_approval(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)
    initialize_database(layout.database_path)

    authorization = authorize_agent_capability(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
        capability="repo.read",
        reason="Read project context.",
    )

    assert authorization.evaluation.decision is CapabilityDecision.ALLOW
    assert authorization.approval_request is None

    with connect_database(layout.database_path) as connection:
        assert list_approvals(connection) == []


def test_authorize_agent_capability_requests_approval_for_gated_capability(
    tmp_path: Path,
) -> None:
    layout = _create_workspace(tmp_path)
    initialize_database(layout.database_path)

    authorization = authorize_agent_capability(
        database_path=layout.database_path,
        layout=layout,
        agent_id="george",
        capability="main.merge",
        reason="Merge reviewed changes.",
        subject_type="run",
        subject_id="RUN-0001",
    )

    assert authorization.evaluation.decision is CapabilityDecision.REQUIRE_APPROVAL
    assert authorization.approval_request is not None
    assert authorization.approval_request.approval.action == "main.merge"
    assert authorization.approval_request.approval.subject_id == "RUN-0001"

    with connect_database(layout.database_path) as connection:
        approvals = list_approvals(connection)
        inbox_items = list_inbox_items(connection, recipient_id="founder")

    assert approvals == [authorization.approval_request.approval]
    assert inbox_items == [authorization.approval_request.inbox_item]


def test_authorize_agent_capability_rejects_denied_capability(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)
    initialize_database(layout.database_path)

    with pytest.raises(PermissionError, match="denied for role"):
        authorize_agent_capability(
            database_path=layout.database_path,
            layout=layout,
            agent_id="supervisor",
            capability="repo.write",
            reason="Write implementation changes.",
        )


def _create_workspace(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)

    return layout
