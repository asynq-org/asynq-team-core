"""Local workspace diagnostics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from asynq_team_core.config import TeamConfig, load_config
from asynq_team_core.database import (
    connect_database,
    get_applied_migration_versions,
    get_expected_migration_versions,
)
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runner_policy import load_runner_policy


class DoctorStatus(str, Enum):
    """Supported doctor check statuses."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class DoctorCheck:
    """A single diagnostic check result."""

    name: str
    status: DoctorStatus
    message: str


@dataclass(frozen=True)
class DoctorReport:
    """Workspace diagnostic report."""

    workspace: Path
    checks: tuple[DoctorCheck, ...]

    @property
    def has_failures(self) -> bool:
        """Return true when any check failed."""
        return any(check.status is DoctorStatus.FAIL for check in self.checks)


def run_doctor(layout: ProjectLayout) -> DoctorReport:
    """Run local workspace diagnostics."""
    config = _load_config_or_none(layout.config_path)
    checks = (
        _check_workspace(layout.workspace),
        _check_team_dir(layout.team_dir),
        _check_config(layout.config_path, config),
        _check_storage_adapter(config),
        _check_database(layout.database_path),
        _check_migrations(layout.database_path),
        _check_required_directories(layout),
        _check_required_files(layout),
        _check_runner_policy(layout),
        _check_git_backup(config),
    )

    return DoctorReport(workspace=layout.workspace, checks=checks)


def _check_workspace(workspace: Path) -> DoctorCheck:
    if workspace.is_dir():
        return DoctorCheck("workspace", DoctorStatus.PASS, f"Workspace exists: {workspace}")
    return DoctorCheck("workspace", DoctorStatus.FAIL, f"Workspace is missing: {workspace}")


def _check_team_dir(team_dir: Path) -> DoctorCheck:
    if team_dir.is_dir():
        return DoctorCheck("team_dir", DoctorStatus.PASS, f"Team directory exists: {team_dir}")
    return DoctorCheck("team_dir", DoctorStatus.FAIL, f"Team directory is missing: {team_dir}")


def _check_config(config_path: Path, config: TeamConfig | None) -> DoctorCheck:
    if not config_path.is_file():
        return DoctorCheck("config", DoctorStatus.FAIL, f"Config is missing: {config_path}")
    if config is None:
        return DoctorCheck("config", DoctorStatus.FAIL, f"Config cannot be loaded: {config_path}")
    return DoctorCheck("config", DoctorStatus.PASS, f"Config is valid: {config_path}")


def _check_storage_adapter(config: TeamConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("storage_adapter", DoctorStatus.FAIL, "Storage adapter cannot be read.")
    if config.storage.adapter == "sqlite":
        return DoctorCheck("storage_adapter", DoctorStatus.PASS, "Storage adapter is sqlite.")
    return DoctorCheck(
        "storage_adapter",
        DoctorStatus.FAIL,
        f"Unsupported storage adapter: {config.storage.adapter}",
    )


def _check_database(database_path: Path) -> DoctorCheck:
    if database_path.is_file():
        return DoctorCheck("database", DoctorStatus.PASS, f"Database exists: {database_path}")
    return DoctorCheck("database", DoctorStatus.FAIL, f"Database is missing: {database_path}")


def _check_migrations(database_path: Path) -> DoctorCheck:
    if not database_path.is_file():
        return DoctorCheck("migrations", DoctorStatus.FAIL, "Database migrations cannot be read.")

    try:
        with connect_database(database_path) as connection:
            applied = get_applied_migration_versions(connection)
    except sqlite3.Error as exc:
        return DoctorCheck("migrations", DoctorStatus.FAIL, f"Database cannot be opened: {exc}")

    expected = get_expected_migration_versions()
    missing = sorted(expected - applied)
    extra = sorted(applied - expected)
    if missing:
        return DoctorCheck(
            "migrations",
            DoctorStatus.FAIL,
            f"Missing database migrations: {_format_versions(missing)}",
        )
    if extra:
        return DoctorCheck(
            "migrations",
            DoctorStatus.WARN,
            f"Database has future migrations: {_format_versions(extra)}",
        )
    return DoctorCheck("migrations", DoctorStatus.PASS, "Database migrations are current.")


def _check_required_directories(layout: ProjectLayout) -> DoctorCheck:
    missing = [
        path.relative_to(layout.workspace).as_posix()
        for path in (
            layout.agents_dir,
            layout.tasks_dir,
            layout.runs_dir,
            layout.adr_dir,
            layout.rules_dir,
            layout.policy_dir,
            layout.backups_dir,
        )
        if not path.is_dir()
    ]
    if missing:
        return DoctorCheck(
            "directories",
            DoctorStatus.FAIL,
            f"Missing directories: {', '.join(missing)}",
        )
    return DoctorCheck("directories", DoctorStatus.PASS, "Required directories exist.")


def _check_required_files(layout: ProjectLayout) -> DoctorCheck:
    required = (
        layout.agents_dir / "ea.yaml",
        layout.agents_dir / "george.yaml",
        layout.agents_dir / "supervisor.yaml",
        layout.rules_dir / "company.md",
        layout.rules_dir / "engineering.md",
        layout.rules_dir / "security.md",
        layout.policy_dir / "approvals.yaml",
        layout.policy_dir / "capabilities.yaml",
        layout.policy_dir / "protected-paths.yaml",
        layout.policy_dir / "runners.yaml",
    )
    missing = [
        path.relative_to(layout.workspace).as_posix() for path in required if not path.is_file()
    ]
    if missing:
        return DoctorCheck("default_files", DoctorStatus.FAIL, f"Missing files: {', '.join(missing)}")
    return DoctorCheck("default_files", DoctorStatus.PASS, "Default agent, rule, and policy files exist.")


def _check_runner_policy(layout: ProjectLayout) -> DoctorCheck:
    try:
        policy = load_runner_policy(layout)
    except (RuntimeError, TypeError, ValueError) as exc:
        return DoctorCheck("runner_policy", DoctorStatus.FAIL, f"Runner policy is invalid: {exc}")

    return DoctorCheck(
        "runner_policy",
        DoctorStatus.PASS,
        f"Runner policy is valid with {len(policy.allowed_tools)} allowed tools.",
    )


def _check_git_backup(config: TeamConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck("git_backup", DoctorStatus.WARN, "Git backup config cannot be read.")
    if not config.git.enabled:
        return DoctorCheck("git_backup", DoctorStatus.WARN, "Git artifact backup is disabled.")
    if not config.git.remote:
        return DoctorCheck("git_backup", DoctorStatus.WARN, "Git artifact backup remote is not configured.")
    return DoctorCheck("git_backup", DoctorStatus.PASS, f"Git artifact backup remote: {config.git.remote}")


def _load_config_or_none(config_path: Path) -> TeamConfig | None:
    if not config_path.is_file():
        return None
    try:
        return load_config(config_path)
    except (RuntimeError, TypeError, ValueError):
        return None


def _format_versions(versions: list[int]) -> str:
    return ", ".join(str(version) for version in versions)
