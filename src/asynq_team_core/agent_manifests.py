"""Project-local agent manifest loading and runner selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runner_policy import load_runner_policy


@dataclass(frozen=True)
class AgentRunnerSettings:
    """Runner and model settings declared by one agent manifest."""

    default: str
    default_model: str
    allowed_models: frozenset[str]
    can_request_model_change: bool
    max_run_budget_usd: float | None


@dataclass(frozen=True)
class AgentManifest:
    """Parsed agent manifest."""

    id: str
    display_name: str
    role: str
    mission: str
    supervisor: str | None
    rule_refs: tuple[str, ...]
    runner: AgentRunnerSettings


@dataclass(frozen=True)
class AgentRunnerSelection:
    """Resolved runner and model for a run."""

    agent_id: str
    runner: str
    model: str
    requested_model: str | None
    max_run_budget_usd: float | None


def load_agent_manifest(layout: ProjectLayout, agent_id: str) -> AgentManifest:
    """Load and validate an agent manifest by id."""
    clean_agent_id = _require_non_empty(agent_id, "agent_id")
    path = layout.agents_dir / f"{clean_agent_id}.yaml"
    _ensure_child_path(layout.agents_dir, path)
    data = _load_yaml_mapping(path, "Agent manifest")
    manifest_id = _get_required_str(data, "id")
    if manifest_id != clean_agent_id:
        raise ValueError(f"Agent manifest id mismatch: {manifest_id} != {clean_agent_id}")

    return AgentManifest(
        id=manifest_id,
        display_name=_get_str(data, "display_name", manifest_id),
        role=_get_required_str(data, "role"),
        mission=_get_str(data, "mission", ""),
        supervisor=_get_optional_str(data, "supervisor"),
        rule_refs=_parse_str_list(data.get("rule_refs", ()), "rule_refs"),
        runner=_parse_runner_settings(_get_mapping(data, "runner")),
    )


def resolve_agent_runner_selection(
    layout: ProjectLayout,
    agent_id: str,
    requested_model: str | None = None,
) -> AgentRunnerSelection:
    """Resolve the runner and model an agent may use for a run."""
    manifest = load_agent_manifest(layout, agent_id)
    runner_policy = load_runner_policy(layout)
    if manifest.runner.default not in runner_policy.allowed_runners:
        raise PermissionError(f"Runner is not allowed by policy: {manifest.runner.default}")

    model = manifest.runner.default_model
    clean_requested_model = None
    if requested_model is not None:
        clean_requested_model = _require_non_empty(requested_model, "requested_model")
        if not manifest.runner.can_request_model_change:
            raise PermissionError(f"Agent cannot request model changes: {agent_id}")
        model = clean_requested_model

    if model not in manifest.runner.allowed_models:
        raise PermissionError(f"Model is not allowed for agent {agent_id}: {model}")

    policy_models = runner_policy.allowed_models_by_runner.get(manifest.runner.default, frozenset())
    if model not in policy_models:
        raise PermissionError(
            f"Model is not allowed for runner {manifest.runner.default}: {model}"
        )

    return AgentRunnerSelection(
        agent_id=manifest.id,
        runner=manifest.runner.default,
        model=model,
        requested_model=clean_requested_model,
        max_run_budget_usd=manifest.runner.max_run_budget_usd,
    )


def _parse_runner_settings(data: dict[str, Any]) -> AgentRunnerSettings:
    default = _get_required_str(data, "default")
    default_model = _get_required_str(data, "default_model")
    allowed_models = frozenset(_parse_str_list(data.get("allowed_models", ()), "allowed_models"))
    if default_model not in allowed_models:
        raise ValueError("Agent runner default_model must be listed in allowed_models.")

    return AgentRunnerSettings(
        default=default,
        default_model=default_model,
        allowed_models=allowed_models,
        can_request_model_change=_get_bool(data, "can_request_model_change", False),
        max_run_budget_usd=_get_optional_float(data, "max_run_budget_usd"),
    )


def _parse_str_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"Agent manifest {field_name} must be a list.")

    return tuple(_require_non_empty(item, f"Agent manifest {field_name} entry") for item in value)


def _load_yaml_mapping(path: Path, document_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{document_name} not found: {path}")

    yaml = _require_yaml()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{document_name} root must be a mapping.")

    return data


def _get_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"Agent manifest {key} must be a mapping.")
    return value


def _get_required_str(data: dict[str, Any], key: str) -> str:
    if key not in data:
        raise ValueError(f"Agent manifest {key} must be a non-empty string.")
    return _require_non_empty(data[key], f"Agent manifest {key}")


def _get_str(data: dict[str, Any], key: str, default: str) -> str:
    return _require_non_empty(data.get(key, default), f"Agent manifest {key}")


def _get_optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return _require_non_empty(value, f"Agent manifest {key}")


def _get_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"Agent manifest {key} must be a boolean.")
    return value


def _get_optional_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"Agent manifest {key} must be a number.")
    if value < 0:
        raise ValueError(f"Agent manifest {key} must not be negative.")
    return float(value)


def _require_non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Agent manifest path escapes parent directory: {child}") from exc


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read Asynq Team agent manifests.") from exc

    return yaml
