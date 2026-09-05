"""Project initialization helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.config import TeamConfig, default_config, write_config
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files

ConfigWriter = Callable[[Path, TeamConfig], None]

RUNTIME_GITIGNORE_ENTRIES = (
    ".team/team.db",
    ".team/backups/*.db",
    ".team/worker/*.pid",
    ".team/worker/*.log",
)


@dataclass(frozen=True)
class ProjectInitialization:
    """Result of initializing project-local runtime state."""

    layout: ProjectLayout
    created_config: bool
    created_default_files: tuple[Path, ...]


def initialize_project(
    workspace: Path,
    project_name: str = "Asynq Team",
    git_enabled: bool = True,
    git_remote: str = "",
    overwrite_config: bool = False,
    overwrite_defaults: bool = False,
    write_config_file: ConfigWriter = write_config,
) -> ProjectInitialization:
    """Create project-local directories and a default config file when needed."""
    layout = get_project_layout(workspace)
    create_project_directories(layout)

    should_write_config = overwrite_config or not layout.config_path.exists()
    if should_write_config:
        write_config_file(
            layout.config_path,
            default_config(
                project_name=project_name,
                git_enabled=git_enabled,
                git_remote=git_remote,
            ),
        )

    created_default_files = seed_default_project_files(layout, overwrite=overwrite_defaults)
    ensure_runtime_gitignore_entries(layout.workspace)

    return ProjectInitialization(
        layout=layout,
        created_config=should_write_config,
        created_default_files=created_default_files,
    )


def ensure_runtime_gitignore_entries(workspace: Path) -> bool:
    """Ensure local runtime files are ignored by the workspace git repo."""
    gitignore_path = workspace / ".gitignore"
    existing_body = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    existing_lines = set(existing_body.splitlines())
    missing_entries = [entry for entry in RUNTIME_GITIGNORE_ENTRIES if entry not in existing_lines]
    if not missing_entries:
        return False

    lines_to_append = ["# Asynq Team local runtime state", *missing_entries]
    separator = "\n" if existing_body and not existing_body.endswith("\n") else ""
    prefix = "\n" if existing_body else ""
    appended_body = "\n".join(lines_to_append)
    gitignore_path.write_text(
        f"{existing_body}{separator}{prefix}{appended_body}\n",
        encoding="utf-8",
    )
    return True
