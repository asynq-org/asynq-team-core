from pathlib import Path

import pytest
import yaml

from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.runner_policy import (
    RunnerToolDecision,
    evaluate_runner_tool,
    load_runner_policy,
)


def test_load_runner_policy_reads_default_tools(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    policy = load_runner_policy(layout)

    assert policy.version == 1
    assert "shell.test" in policy.allowed_tools
    assert "codex.runner" in policy.allowed_tools
    assert "shell.destructive" in policy.denied_tools


def test_evaluate_runner_tool_allows_default_tool(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_runner_tool(layout, "shell.test")

    assert evaluation.tool == "shell.test"
    assert evaluation.decision is RunnerToolDecision.ALLOW


def test_evaluate_runner_tool_denies_default_denied_tool(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_runner_tool(layout, "shell.destructive")

    assert evaluation.tool == "shell.destructive"
    assert evaluation.decision is RunnerToolDecision.DENY
    assert "denied" in evaluation.reason


def test_evaluate_runner_tool_denies_unlisted_tool(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    evaluation = evaluate_runner_tool(layout, "browser.write")

    assert evaluation.decision is RunnerToolDecision.DENY
    assert "not listed" in evaluation.reason


def test_evaluate_runner_tool_prefers_explicit_deny(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)
    _add_allowed_tool(layout, "shell.destructive")

    evaluation = evaluate_runner_tool(layout, "shell.destructive")

    assert evaluation.decision is RunnerToolDecision.DENY


def test_load_runner_policy_rejects_invalid_lists(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)
    path = layout.policy_dir / "runners.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["allowed_tools"] = "shell.read"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(TypeError, match="Runner policy allowed_tools must be a list"):
        load_runner_policy(layout)


def test_evaluate_runner_tool_rejects_empty_tool(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    with pytest.raises(ValueError, match="tool must be a non-empty string"):
        evaluate_runner_tool(layout, " ")


def _create_workspace(tmp_path: Path) -> ProjectLayout:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)

    return layout


def _add_allowed_tool(layout: ProjectLayout, tool: str) -> None:
    path = layout.policy_dir / "runners.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.setdefault("allowed_tools", []).append(tool)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
