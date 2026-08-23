"""Filesystem path helpers for project-local Asynq Team state."""

from pathlib import Path


DEFAULT_TEAM_DIR_NAME = ".team"
DEFAULT_CONFIG_FILE_NAME = "config.yaml"


def get_team_dir(workspace: Path) -> Path:
    """Return the project-local Asynq Team directory for a workspace."""
    return workspace / DEFAULT_TEAM_DIR_NAME


def get_config_path(workspace: Path) -> Path:
    """Return the default project-local config path for a workspace."""
    return get_team_dir(workspace) / DEFAULT_CONFIG_FILE_NAME

