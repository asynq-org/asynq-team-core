"""SQLite database initialization and event persistence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.events import Event, format_event_time, utc_now


@dataclass(frozen=True)
class Migration:
    """A single explicit SQLite migration."""

    version: int
    name: str
    sql: str


MIGRATIONS = (
    Migration(
        version=1,
        name="create_events",
        sql="""
        create table if not exists events (
            id text primary key,
            type text not null,
            entity_type text not null,
            entity_id text not null,
            actor_type text not null,
            actor_id text not null,
            payload_json text not null,
            created_at text not null,
            prev_hash text,
            hash text not null
        );

        create index if not exists idx_events_entity
            on events (entity_type, entity_id, created_at);

        create index if not exists idx_events_type
            on events (type, created_at);
        """,
    ),
)


def connect_database(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection for the runtime database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


def initialize_database(path: Path) -> None:
    """Create or migrate the runtime database."""
    with connect_database(path) as connection:
        _ensure_schema_migrations(connection)
        _apply_pending_migrations(connection)


def insert_event(connection: sqlite3.Connection, event: Event) -> None:
    """Persist an event record."""
    record = event.to_record()
    connection.execute(
        """
        insert into events (
            id,
            type,
            entity_type,
            entity_id,
            actor_type,
            actor_id,
            payload_json,
            created_at,
            prev_hash,
            hash
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["type"],
            record["entity_type"],
            record["entity_id"],
            record["actor_type"],
            record["actor_id"],
            record["payload_json"],
            record["created_at"],
            record["prev_hash"],
            record["hash"],
        ),
    )


def get_applied_migration_versions(connection: sqlite3.Connection) -> set[int]:
    """Return applied migration versions."""
    _ensure_schema_migrations(connection)
    rows = connection.execute("select version from schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def _ensure_schema_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists schema_migrations (
            version integer primary key,
            name text not null,
            applied_at text not null
        )
        """
    )


def _apply_pending_migrations(connection: sqlite3.Connection) -> None:
    applied_versions = get_applied_migration_versions(connection)
    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue
        connection.executescript(migration.sql)
        connection.execute(
            """
            insert into schema_migrations (version, name, applied_at)
            values (?, ?, ?)
            """,
            (migration.version, migration.name, format_event_time(utc_now())),
        )
