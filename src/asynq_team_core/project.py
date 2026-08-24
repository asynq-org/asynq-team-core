"""Project initialization helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.config import TeamConfig, default_config, write_config
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files

ConfigWriter = Callable[[Path, TeamConfig], None]


@dataclass(frozen=True)
class ProjectInitialization:
    """Result of initializing project-local runtime state."""

    layout: ProjectLayout
    created_config: bool
    created_default_files: tuple[Path, ...]


def initialize_project(
    workspace: Path,
    project_name: str = "Asynq Team",
    overwrite_config: bool = False,
    overwrite_defaults: bool = False,
    write_config_file: ConfigWriter = write_config,
) -> ProjectInitialization:
    """Create project-local directories and a default config file when needed."""
    layout = get_project_layout(workspace)
    create_project_directories(layout)

    should_write_config = overwrite_config or not layout.config_path.exists()
    if should_write_config:
        write_config_file(layout.config_path, default_config(project_name=project_name))

    created_default_files = seed_default_project_files(layout, overwrite=overwrite_defaults)

    return ProjectInitialization(
        layout=layout,
        created_config=should_write_config,
        created_default_files=created_default_files,
    )
