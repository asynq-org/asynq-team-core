"""Project-local capability policy loading and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from asynq_team_core.agent_manifests import load_agent_manifest
from asynq_team_core.approvals import (
    ApprovalRequest,
    ApprovalStatus,
    find_matching_approval,
    request_approval,
)
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout


class CapabilityDecision(str, Enum):
    """Decision for a requested agent capability."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class RoleCapabilityPolicy:
    """Capability rules for one role."""

    allow: frozenset[str]
    require_approval: frozenset[str]
    deny: frozenset[str]


@dataclass(frozen=True)
class CapabilityPolicy:
    """Parsed capability policy."""

    version: int
    roles: dict[str, RoleCapabilityPolicy]


@dataclass(frozen=True)
class CapabilityEvaluation:
    """Result of evaluating one capability for one agent."""

    agent_id: str
    role: str
    capability: str
    decision: CapabilityDecision
    reason: str


@dataclass(frozen=True)
class CapabilityAuthorization:
    """Result of authorizing one requested capability."""

    evaluation: CapabilityEvaluation
    approval_request: ApprovalRequest | None


def load_capability_policy(layout: ProjectLayout) -> CapabilityPolicy:
    """Load and validate project-local capability policy."""
    policy_path = layout.policy_dir / "capabilities.yaml"
    _ensure_child_path(layout.policy_dir, policy_path)
    data = _load_yaml_mapping(policy_path, "Capability policy")
    version = data.get("version")
    if not isinstance(version, int):
        raise TypeError("Capability policy version must be an integer.")

    roles_data = data.get("roles")
    if not isinstance(roles_data, dict):
        raise TypeError("Capability policy roles must be a mapping.")

    roles = {
        role: _parse_role_capability_policy(role, value) for role, value in roles_data.items()
    }
    return CapabilityPolicy(version=version, roles=roles)


def evaluate_agent_capability(
    layout: ProjectLayout,
    agent_id: str,
    capability: str,
) -> CapabilityEvaluation:
    """Evaluate whether an agent may use a capability."""
    role = _load_agent_role(layout, agent_id)
    policy = load_capability_policy(layout)
    role_policy = policy.roles.get(role)
    if role_policy is None:
        return CapabilityEvaluation(
            agent_id=agent_id,
            role=role,
            capability=capability,
            decision=CapabilityDecision.DENY,
            reason=f"Role is not defined in capability policy: {role}",
        )

    if capability in role_policy.deny:
        return CapabilityEvaluation(
            agent_id=agent_id,
            role=role,
            capability=capability,
            decision=CapabilityDecision.DENY,
            reason=f"Capability is denied for role: {role}",
        )
    if capability in role_policy.require_approval:
        return CapabilityEvaluation(
            agent_id=agent_id,
            role=role,
            capability=capability,
            decision=CapabilityDecision.REQUIRE_APPROVAL,
            reason=f"Capability requires approval for role: {role}",
        )
    if capability in role_policy.allow:
        return CapabilityEvaluation(
            agent_id=agent_id,
            role=role,
            capability=capability,
            decision=CapabilityDecision.ALLOW,
            reason=f"Capability is allowed for role: {role}",
        )

    return CapabilityEvaluation(
        agent_id=agent_id,
        role=role,
        capability=capability,
        decision=CapabilityDecision.DENY,
        reason=f"Capability is not listed for role: {role}",
    )


def authorize_agent_capability(
    database_path: Path,
    layout: ProjectLayout,
    agent_id: str,
    capability: str,
    reason: str,
    approver_id: str = "founder",
    subject_type: str | None = None,
    subject_id: str | None = None,
    clock: Clock = utc_now,
) -> CapabilityAuthorization:
    """Authorize a capability or create the required approval request."""
    evaluation = evaluate_agent_capability(layout, agent_id, capability)
    if evaluation.decision is CapabilityDecision.ALLOW:
        return CapabilityAuthorization(evaluation=evaluation, approval_request=None)
    if evaluation.decision is CapabilityDecision.DENY:
        raise PermissionError(evaluation.reason)

    with connect_database(database_path) as connection:
        granted = find_matching_approval(
            connection,
            action=capability,
            requester_type="agent",
            requester_id=agent_id,
            status=ApprovalStatus.GRANTED,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        if granted is not None:
            return CapabilityAuthorization(evaluation=evaluation, approval_request=None)

        approval_request = request_approval(
            connection,
            action=capability,
            reason=reason,
            requester_type="agent",
            requester_id=agent_id,
            approver_id=approver_id,
            subject_type=subject_type,
            subject_id=subject_id,
            clock=clock,
        )

    return CapabilityAuthorization(evaluation=evaluation, approval_request=approval_request)


def _parse_role_capability_policy(role: Any, value: Any) -> RoleCapabilityPolicy:
    if not isinstance(role, str) or not role.strip():
        raise ValueError("Capability policy role names must be non-empty strings.")
    if not isinstance(value, dict):
        raise TypeError(f"Capability policy role must be a mapping: {role}")

    return RoleCapabilityPolicy(
        allow=frozenset(_parse_capability_list(value.get("allow", ()), role, "allow")),
        require_approval=frozenset(
            _parse_capability_list(value.get("require_approval", ()), role, "require_approval")
        ),
        deny=frozenset(_parse_capability_list(value.get("deny", ()), role, "deny")),
    )


def _parse_capability_list(value: Any, role: str, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"Capability policy {role}.{field} must be a list.")

    capabilities: list[str] = []
    for capability in value:
        if not isinstance(capability, str) or not capability.strip():
            raise ValueError(f"Capability policy {role}.{field} entries must be non-empty strings.")
        capabilities.append(capability.strip())

    return tuple(capabilities)


def _load_agent_role(layout: ProjectLayout, agent_id: str) -> str:
    return load_agent_manifest(layout, agent_id).role


def _load_yaml_mapping(path: Path, document_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{document_name} not found: {path}")

    yaml = _require_yaml()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{document_name} root must be a mapping.")

    return data


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Policy path escapes parent directory: {child}") from exc


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read Asynq Team policy files.") from exc

    return yaml
