"""Project-local runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _get_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{key}' must be a mapping.")
    return value


def _get_str(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"Config value '{key}' must be a string.")
    return value


def _get_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Config value '{key}' must be a boolean.")
    return value


def _get_int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"Config value '{key}' must be an integer.")
    return value


@dataclass(frozen=True)
class ProjectConfig:
    """Project identity settings."""

    name: str = "Asynq Team"

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ProjectConfig:
        """Create project config from a parsed mapping."""
        return cls(name=_get_str(data, "name", cls.name))

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {"name": self.name}


@dataclass(frozen=True)
class StorageConfig:
    """Structured state storage settings."""

    adapter: str = "sqlite"
    sqlite_path: str = ".team/team.db"

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> StorageConfig:
        """Create storage config from a parsed mapping."""
        return cls(
            adapter=_get_str(data, "adapter", cls.adapter),
            sqlite_path=_get_str(data, "sqlite_path", cls.sqlite_path),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {"adapter": self.adapter, "sqlite_path": self.sqlite_path}


@dataclass(frozen=True)
class BackupRetentionConfig:
    """Local database backup retention settings."""

    keep_last: int = 20
    keep_daily: int = 14
    keep_weekly: int = 8
    keep_monthly: int = 12

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> BackupRetentionConfig:
        """Create retention config from a parsed mapping."""
        return cls(
            keep_last=_get_int(data, "keep_last", cls.keep_last),
            keep_daily=_get_int(data, "keep_daily", cls.keep_daily),
            keep_weekly=_get_int(data, "keep_weekly", cls.keep_weekly),
            keep_monthly=_get_int(data, "keep_monthly", cls.keep_monthly),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {
            "keep_last": self.keep_last,
            "keep_daily": self.keep_daily,
            "keep_weekly": self.keep_weekly,
            "keep_monthly": self.keep_monthly,
        }


@dataclass(frozen=True)
class BackupScheduleConfig:
    """Local database backup schedule settings."""

    enabled: bool = False
    cron: str = "0 * * * *"

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> BackupScheduleConfig:
        """Create backup schedule config from a parsed mapping."""
        return cls(
            enabled=_get_bool(data, "enabled", cls.enabled),
            cron=_get_str(data, "cron", cls.cron),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {"enabled": self.enabled, "cron": self.cron}


@dataclass(frozen=True)
class BackupConfig:
    """Local database backup settings."""

    enabled: bool = True
    directory: str = ".team/backups"
    retention: BackupRetentionConfig = field(default_factory=BackupRetentionConfig)
    schedule: BackupScheduleConfig = field(default_factory=BackupScheduleConfig)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> BackupConfig:
        """Create backup config from a parsed mapping."""
        return cls(
            enabled=_get_bool(data, "enabled", cls.enabled),
            directory=_get_str(data, "directory", cls.directory),
            retention=BackupRetentionConfig.from_mapping(_get_mapping(data, "retention")),
            schedule=BackupScheduleConfig.from_mapping(_get_mapping(data, "schedule")),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {
            "enabled": self.enabled,
            "directory": self.directory,
            "retention": self.retention.to_mapping(),
            "schedule": self.schedule.to_mapping(),
        }


@dataclass(frozen=True)
class GitConfig:
    """Git artifact backup settings."""

    enabled: bool = True
    remote: str = ""
    push_task_artifacts: bool = True
    push_run_artifacts: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> GitConfig:
        """Create git config from a parsed mapping."""
        return cls(
            enabled=_get_bool(data, "enabled", cls.enabled),
            remote=_get_str(data, "remote", cls.remote),
            push_task_artifacts=_get_bool(
                data, "push_task_artifacts", cls.push_task_artifacts
            ),
            push_run_artifacts=_get_bool(data, "push_run_artifacts", cls.push_run_artifacts),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {
            "enabled": self.enabled,
            "remote": self.remote,
            "push_task_artifacts": self.push_task_artifacts,
            "push_run_artifacts": self.push_run_artifacts,
        }


@dataclass(frozen=True)
class TeamConfig:
    """Root runtime configuration."""

    project: ProjectConfig = field(default_factory=ProjectConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    git: GitConfig = field(default_factory=GitConfig)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> TeamConfig:
        """Create runtime config from a parsed mapping."""
        return cls(
            project=ProjectConfig.from_mapping(_get_mapping(data, "project")),
            storage=StorageConfig.from_mapping(_get_mapping(data, "storage")),
            backup=BackupConfig.from_mapping(_get_mapping(data, "backup")),
            git=GitConfig.from_mapping(_get_mapping(data, "git")),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return {
            "project": self.project.to_mapping(),
            "storage": self.storage.to_mapping(),
            "backup": self.backup.to_mapping(),
            "git": self.git.to_mapping(),
        }


def default_config(project_name: str = "Asynq Team") -> TeamConfig:
    """Return the default project-local runtime configuration."""
    return TeamConfig(project=ProjectConfig(name=project_name))


def load_config(path: Path) -> TeamConfig:
    """Load runtime config from a YAML file."""
    yaml = _require_yaml()

    with path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping.")

    return TeamConfig.from_mapping(data)


def write_config(path: Path, config: TeamConfig) -> None:
    """Write runtime config to a YAML file."""
    yaml = _require_yaml()

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as config_file:
        yaml.safe_dump(config.to_mapping(), config_file, sort_keys=False)


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read and write Asynq Team config.") from exc

    return yaml
