"""Filesystem path helpers for project-local Asynq Team state."""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEAM_DIR_NAME = ".team"
DEFAULT_CONFIG_FILE_NAME = "config.yaml"


def get_team_dir(workspace: Path) -> Path:
    """Return the project-local Asynq Team directory for a workspace."""
    return workspace / DEFAULT_TEAM_DIR_NAME


def get_config_path(workspace: Path) -> Path:
    """Return the default project-local config path for a workspace."""
    return get_team_dir(workspace) / DEFAULT_CONFIG_FILE_NAME


@dataclass(frozen=True)
class ProjectLayout:
    """Resolved project-local paths used by the core runtime."""

    workspace: Path
    team_dir: Path
    config_path: Path
    agents_dir: Path
    tasks_dir: Path
    runs_dir: Path
    adr_dir: Path
    policy_dir: Path
    backups_dir: Path
    database_path: Path


def get_project_layout(workspace: Path) -> ProjectLayout:
    """Return the default project-local runtime layout for a workspace."""
    team_dir = get_team_dir(workspace)

    return ProjectLayout(
        workspace=workspace,
        team_dir=team_dir,
        config_path=get_config_path(workspace),
        agents_dir=team_dir / "agents",
        tasks_dir=team_dir / "tasks",
        runs_dir=team_dir / "runs",
        adr_dir=team_dir / "adr",
        policy_dir=team_dir / "policy",
        backups_dir=team_dir / "backups",
        database_path=team_dir / "team.db",
    )


def create_project_directories(layout: ProjectLayout) -> None:
    """Create the directories needed for local runtime state."""
    for path in (
        layout.team_dir,
        layout.agents_dir,
        layout.tasks_dir,
        layout.runs_dir,
        layout.adr_dir,
        layout.policy_dir,
        layout.backups_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
