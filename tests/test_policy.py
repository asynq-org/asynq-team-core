from pathlib import Path

import pytest

from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.policy import (
    CapabilityDecision,
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


def _create_workspace(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)

    return layout
