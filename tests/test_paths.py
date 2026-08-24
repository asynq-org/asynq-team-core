from pathlib import Path

from asynq_team_core.paths import (
    create_project_directories,
    get_config_path,
    get_project_layout,
    get_team_dir,
)


def test_get_team_dir_uses_project_local_directory() -> None:
    assert get_team_dir(Path("/workspace")) == Path("/workspace/.team")


def test_get_config_path_uses_default_config_file() -> None:
    assert get_config_path(Path("/workspace")) == Path("/workspace/.team/config.yaml")


def test_get_project_layout_resolves_runtime_paths() -> None:
    layout = get_project_layout(Path("/workspace"))

    assert layout.workspace == Path("/workspace")
    assert layout.team_dir == Path("/workspace/.team")
    assert layout.config_path == Path("/workspace/.team/config.yaml")
    assert layout.agents_dir == Path("/workspace/.team/agents")
    assert layout.tasks_dir == Path("/workspace/.team/tasks")
    assert layout.runs_dir == Path("/workspace/.team/runs")
    assert layout.adr_dir == Path("/workspace/.team/adr")
    assert layout.rules_dir == Path("/workspace/.team/rules")
    assert layout.policy_dir == Path("/workspace/.team/policy")
    assert layout.backups_dir == Path("/workspace/.team/backups")
    assert layout.database_path == Path("/workspace/.team/team.db")


def test_create_project_directories_creates_runtime_dirs(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)

    create_project_directories(layout)

    assert layout.team_dir.is_dir()
    assert layout.agents_dir.is_dir()
    assert layout.tasks_dir.is_dir()
    assert layout.runs_dir.is_dir()
    assert layout.adr_dir.is_dir()
    assert layout.rules_dir.is_dir()
    assert layout.policy_dir.is_dir()
    assert layout.backups_dir.is_dir()
    assert not layout.database_path.exists()
