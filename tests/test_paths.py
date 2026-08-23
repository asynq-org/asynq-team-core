from pathlib import Path

from asynq_team_core.paths import get_config_path, get_team_dir


def test_get_team_dir_uses_project_local_directory() -> None:
    assert get_team_dir(Path("/workspace")) == Path("/workspace/.team")


def test_get_config_path_uses_default_config_file() -> None:
    assert get_config_path(Path("/workspace")) == Path("/workspace/.team/config.yaml")

