from asynq_team_core.config import TeamConfig, default_config


def test_default_config_uses_documented_storage_paths() -> None:
    config = default_config()

    assert config.project.name == "Asynq Team"
    assert config.storage.adapter == "sqlite"
    assert config.storage.sqlite_path == ".team/team.db"
    assert config.backup.directory == ".team/backups"
    assert config.git.push_task_artifacts is True
    assert config.git.push_run_artifacts is True


def test_config_round_trips_through_mapping() -> None:
    original = default_config(project_name="Example")

    parsed = TeamConfig.from_mapping(original.to_mapping())

    assert parsed == original


def test_partial_mapping_uses_defaults() -> None:
    config = TeamConfig.from_mapping({"project": {"name": "Example"}})

    assert config.project.name == "Example"
    assert config.storage.adapter == "sqlite"
    assert config.backup.enabled is True
    assert config.git.enabled is True
