"""Local SQLite database backups."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from asynq_team_core.database import connect_database, insert_event
from asynq_team_core.events import Clock, create_event, format_event_time, utc_now
from asynq_team_core.paths import ProjectLayout

BACKUP_PREFIX = "team-"
BACKUP_SUFFIX = ".db"


@dataclass(frozen=True)
class DatabaseBackup:
    """A project-local database backup file."""

    path: Path
    relative_path: str
    created_at: str
    size_bytes: int


def create_database_backup(
    database_path: Path,
    layout: ProjectLayout,
    actor_type: str,
    actor_id: str,
    clock: Clock = utc_now,
) -> DatabaseBackup:
    """Create a project-local SQLite database backup and record an audit event."""
    if not database_path.is_file():
        raise ValueError(f"Database is missing: {database_path}")

    created_at_dt = clock()
    created_at = format_event_time(created_at_dt)
    backup_path = _backup_path(layout, created_at_dt)
    temp_path = backup_path.with_suffix(f"{backup_path.suffix}.tmp")
    _ensure_child_path(layout.backups_dir, backup_path)
    layout.backups_dir.mkdir(parents=True, exist_ok=True)

    with connect_database(database_path) as source:
        insert_event(
            source,
            create_event(
                event_type="database.backup_created",
                entity_type="database_backup",
                entity_id=backup_path.name,
                actor_type=actor_type,
                actor_id=actor_id,
                payload={"backup_path": backup_path.relative_to(layout.workspace).as_posix()},
                clock=lambda: created_at_dt,
            ),
        )
        source.commit()
        with sqlite3.connect(temp_path) as destination:
            source.backup(destination)

    temp_path.replace(backup_path)
    return _backup_from_path(layout, backup_path, created_at=created_at)


def list_database_backups(layout: ProjectLayout, limit: int = 50) -> list[DatabaseBackup]:
    """Return local database backups ordered newest first."""
    if limit < 1:
        raise ValueError("limit must be a positive integer.")
    if not layout.backups_dir.is_dir():
        return []

    paths = sorted(
        (path for path in layout.backups_dir.iterdir() if _is_database_backup(path)),
        reverse=True,
    )
    return [_backup_from_path(layout, path) for path in paths[:limit]]


def _is_database_backup(path: Path) -> bool:
    return (
        path.is_file()
        and path.name.startswith(BACKUP_PREFIX)
        and path.name.endswith(BACKUP_SUFFIX)
    )


def _backup_path(layout: ProjectLayout, created_at: datetime) -> Path:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    timestamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return layout.backups_dir / f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}"


def _backup_from_path(
    layout: ProjectLayout,
    path: Path,
    created_at: str | None = None,
) -> DatabaseBackup:
    stat = path.stat()
    backup_created_at = created_at or format_event_time(datetime.fromtimestamp(stat.st_mtime, UTC))
    return DatabaseBackup(
        path=path,
        relative_path=path.relative_to(layout.workspace).as_posix(),
        created_at=backup_created_at,
        size_bytes=stat.st_size,
    )


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Backup path escapes parent directory: {child}") from exc
