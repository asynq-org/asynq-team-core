"""Project initialization helpers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from asynq_team_core.config import TeamConfig, default_config, write_config
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout


ConfigWriter = Callable[[Path, TeamConfig], None]


@dataclass(frozen=True)
class ProjectInitialization:
    """Result of initializing project-local runtime state."""

    layout: ProjectLayout
    created_config: bool


def initialize_project(
    workspace: Path,
    project_name: str = "Asynq Team",
    overwrite_config: bool = False,
    write_config_file: ConfigWriter = write_config,
) -> ProjectInitialization:
    """Create project-local directories and a default config file when needed."""
    layout = get_project_layout(workspace)
    create_project_directories(layout)

    should_write_config = overwrite_config or not layout.config_path.exists()
    if should_write_config:
        write_config_file(layout.config_path, default_config(project_name=project_name))

    return ProjectInitialization(layout=layout, created_config=should_write_config)
