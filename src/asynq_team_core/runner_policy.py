"""Project-local runner tool policy loading and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from asynq_team_core.paths import ProjectLayout


class RunnerToolDecision(str, Enum):
    """Decision for a requested runner tool."""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class RunnerAdapterConfig:
    """Configured runner adapter metadata."""

    name: str
    adapter: str
    command_template: tuple[str, ...]
    working_directory: str


@dataclass(frozen=True)
class RunnerPolicy:
    """Parsed runner tool policy."""

    version: int
    allowed_tools: frozenset[str]
    denied_tools: frozenset[str]
    allowed_runners: frozenset[str]
    allowed_models_by_runner: dict[str, frozenset[str]]
    adapters_by_runner: dict[str, RunnerAdapterConfig]


@dataclass(frozen=True)
class RunnerToolEvaluation:
    """Result of evaluating one runner tool request."""

    tool: str
    decision: RunnerToolDecision
    reason: str


def load_runner_policy(layout: ProjectLayout) -> RunnerPolicy:
    """Load and validate project-local runner tool policy."""
    policy_path = layout.policy_dir / "runners.yaml"
    _ensure_child_path(layout.policy_dir, policy_path)
    data = _load_yaml_mapping(policy_path, "Runner policy")
    version = data.get("version")
    if not isinstance(version, int):
        raise TypeError("Runner policy version must be an integer.")

    return RunnerPolicy(
        version=version,
        allowed_tools=frozenset(_parse_tool_list(data.get("allowed_tools", ()), "allowed_tools")),
        denied_tools=frozenset(_parse_tool_list(data.get("denied_tools", ()), "denied_tools")),
        allowed_runners=frozenset(_parse_runner_mapping(data.get("runners", {}))),
        allowed_models_by_runner=_parse_allowed_models_by_runner(data.get("runners", {})),
        adapters_by_runner=_parse_adapters_by_runner(data.get("runners", {})),
    )


def evaluate_runner_tool(layout: ProjectLayout, tool: str) -> RunnerToolEvaluation:
    """Evaluate whether a runner tool is allowed by project policy."""
    clean_tool = _require_non_empty(tool, "tool")
    policy = load_runner_policy(layout)

    if clean_tool in policy.denied_tools:
        return RunnerToolEvaluation(
            tool=clean_tool,
            decision=RunnerToolDecision.DENY,
            reason=f"Runner tool is denied: {clean_tool}",
        )
    if clean_tool in policy.allowed_tools:
        return RunnerToolEvaluation(
            tool=clean_tool,
            decision=RunnerToolDecision.ALLOW,
            reason=f"Runner tool is allowed: {clean_tool}",
        )

    return RunnerToolEvaluation(
        tool=clean_tool,
        decision=RunnerToolDecision.DENY,
        reason=f"Runner tool is not listed: {clean_tool}",
    )


def _parse_tool_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"Runner policy {field_name} must be a list.")

    tools: list[str] = []
    for tool in value:
        tools.append(_require_non_empty(tool, f"Runner policy {field_name} entry"))

    return tuple(tools)


def _parse_runner_mapping(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        raise TypeError("Runner policy runners must be a mapping.")
    return tuple(_require_non_empty(runner, "Runner policy runner name") for runner in value)


def _parse_allowed_models_by_runner(value: Any) -> dict[str, frozenset[str]]:
    if not isinstance(value, dict):
        raise TypeError("Runner policy runners must be a mapping.")

    models_by_runner: dict[str, frozenset[str]] = {}
    for runner, runner_data in value.items():
        clean_runner = _require_non_empty(runner, "Runner policy runner name")
        if not isinstance(runner_data, dict):
            raise TypeError(f"Runner policy runner must be a mapping: {clean_runner}")
        models = _parse_tool_list(runner_data.get("allowed_models", ()), "allowed_models")
        models_by_runner[clean_runner] = frozenset(models)

    return models_by_runner


def _parse_adapters_by_runner(value: Any) -> dict[str, RunnerAdapterConfig]:
    if not isinstance(value, dict):
        raise TypeError("Runner policy runners must be a mapping.")

    adapters: dict[str, RunnerAdapterConfig] = {}
    for runner, runner_data in value.items():
        clean_runner = _require_non_empty(runner, "Runner policy runner name")
        if not isinstance(runner_data, dict):
            raise TypeError(f"Runner policy runner must be a mapping: {clean_runner}")
        adapters[clean_runner] = RunnerAdapterConfig(
            name=clean_runner,
            adapter=_get_str(runner_data, "adapter", clean_runner),
            command_template=_parse_tool_list(
                runner_data.get("command_template", ()),
                "command_template",
            ),
            working_directory=_get_str(runner_data, "working_directory", "."),
        )

    return adapters


def _load_yaml_mapping(path: Path, document_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{document_name} not found: {path}")

    yaml = _require_yaml()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{document_name} root must be a mapping.")

    return data


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _get_str(data: dict[str, Any], field_name: str, default: str) -> str:
    value = data.get(field_name, default)
    return _require_non_empty(value, f"Runner policy {field_name}")


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Runner policy path escapes parent directory: {child}") from exc


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read Asynq Team runner policy files.") from exc

    return yaml
