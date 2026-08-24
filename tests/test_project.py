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
    assert result.layout.rules_dir.is_dir()
    assert result.layout.policy_dir.is_dir()
    assert result.layout.agents_dir.joinpath("george.yaml").is_file()
    assert result.layout.rules_dir.joinpath("engineering.md").is_file()
    assert result.layout.policy_dir.joinpath("capabilities.yaml").is_file()
    assert result.layout.policy_dir.joinpath("approvals.yaml").is_file()
    assert result.created_default_files
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


def test_initialize_project_preserves_existing_default_files(tmp_path: Path) -> None:
    policy_path = tmp_path / ".team" / "policy" / "capabilities.yaml"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text("custom: true\n", encoding="utf-8")

    initialize_project(tmp_path)

    assert policy_path.read_text(encoding="utf-8") == "custom: true\n"


def test_initialize_project_can_overwrite_default_files(tmp_path: Path) -> None:
    policy_path = tmp_path / ".team" / "policy" / "capabilities.yaml"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text("custom: true\n", encoding="utf-8")

    initialize_project(tmp_path, overwrite_defaults=True)

    assert "roles:" in policy_path.read_text(encoding="utf-8")


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
