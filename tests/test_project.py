from pathlib import Path

from asynq_team_core.config import TeamConfig
from asynq_team_core.project import initialize_project


def test_initialize_project_creates_directories_and_config(tmp_path: Path) -> None:
    writes: list[tuple[Path, TeamConfig]] = []

    result = initialize_project(
        tmp_path,
        project_name="Example",
        write_config_file=lambda path, config: writes.append((path, config)),
    )

    assert result.created_config is True
    assert result.layout.team_dir.is_dir()
    assert result.layout.agents_dir.is_dir()
    assert result.layout.tasks_dir.is_dir()
    assert result.layout.runs_dir.is_dir()
    assert result.layout.policy_dir.is_dir()
    assert writes[0][0] == result.layout.config_path
    assert writes[0][1].project.name == "Example"


def test_initialize_project_preserves_existing_config(tmp_path: Path) -> None:
    writes: list[tuple[Path, TeamConfig]] = []
    config_path = tmp_path / ".team" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("project:\n  name: Existing\n", encoding="utf-8")

    result = initialize_project(
        tmp_path,
        project_name="Example",
        write_config_file=lambda path, config: writes.append((path, config)),
    )

    assert result.created_config is False
    assert writes == []


def test_initialize_project_can_overwrite_config(tmp_path: Path) -> None:
    writes: list[tuple[Path, TeamConfig]] = []
    config_path = tmp_path / ".team" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("project:\n  name: Existing\n", encoding="utf-8")

    result = initialize_project(
        tmp_path,
        project_name="Example",
        overwrite_config=True,
        write_config_file=lambda path, config: writes.append((path, config)),
    )

    assert result.created_config is True
    assert writes[0][0] == result.layout.config_path
    assert writes[0][1].project.name == "Example"
