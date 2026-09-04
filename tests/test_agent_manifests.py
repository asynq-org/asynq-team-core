from pathlib import Path

import pytest
import yaml

from asynq_team_core.agent_manifests import (
    load_agent_manifest,
    resolve_agent_runner_selection,
)
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files


def test_load_agent_manifest_reads_default_runner_settings(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    manifest = load_agent_manifest(layout, "george")

    assert manifest.id == "george"
    assert manifest.role == "engineer"
    assert manifest.runner.default == "codex"
    assert manifest.runner.default_model == "gpt-5-codex"
    assert manifest.runner.allowed_models == frozenset({"gpt-5-codex"})
    assert manifest.runner.can_request_model_change is True
    assert manifest.runner.max_run_budget_usd == 5.0


def test_resolve_agent_runner_selection_uses_default_model(tmp_path: Path) -> None:
    layout = _create_workspace(tmp_path)

    selection = resolve_agent_runner_selection(layout, "george")

    assert selection.agent_id == "george"
    assert selection.runner == "codex"
    assert selection.model == "gpt-5-codex"
    assert selection.requested_model is None


def test_resolve_agent_runner_selection_rejects_model_outside_manifest(
    tmp_path: Path,
) -> None:
    layout = _create_workspace(tmp_path)

    with pytest.raises(PermissionError, match="Model is not allowed for agent george"):
        resolve_agent_runner_selection(layout, "george", requested_model="other-model")


def test_resolve_agent_runner_selection_rejects_model_outside_runner_policy(
    tmp_path: Path,
) -> None:
    layout = _create_workspace(tmp_path)
    _add_agent_allowed_model(layout, "george", "gpt-5-large")

    with pytest.raises(PermissionError, match="Model is not allowed for runner codex"):
        resolve_agent_runner_selection(layout, "george", requested_model="gpt-5-large")


def test_load_agent_manifest_rejects_default_model_outside_allowed_models(
    tmp_path: Path,
) -> None:
    layout = _create_workspace(tmp_path)
    path = layout.agents_dir / "george.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["runner"]["default_model"] = "gpt-5-large"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="default_model"):
        load_agent_manifest(layout, "george")


def _create_workspace(tmp_path: Path) -> ProjectLayout:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)

    return layout


def _add_agent_allowed_model(layout: ProjectLayout, agent_id: str, model: str) -> None:
    path = layout.agents_dir / f"{agent_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["runner"]["allowed_models"].append(model)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
