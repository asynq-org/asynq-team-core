"""SQLite persistence adapter for the local-first MVP runtime."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.events import Event, format_event_time, utc_now
from asynq_team_core.ids import format_sequential_id

SQLiteConnection = sqlite3.Connection
SQLiteRow = sqlite3.Row


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
    Migration(
        version=2,
        name="create_id_counters",
        sql="""
        create table if not exists id_counters (
            name text primary key,
            next_value integer not null
        );
        """,
    ),
    Migration(
        version=3,
        name="create_tasks",
        sql="""
        create table if not exists tasks (
            id text primary key,
            title text not null,
            status text not null,
            priority text not null,
            assignee_id text,
            brief_artifact_path text,
            created_at text not null,
            updated_at text not null
        );

        create index if not exists idx_tasks_status
            on tasks (status, updated_at);

        create index if not exists idx_tasks_assignee
            on tasks (assignee_id, status);
        """,
    ),
    Migration(
        version=4,
        name="create_human_attention_tables",
        sql="""
        create table if not exists approvals (
            id text primary key,
            action text not null,
            reason text not null,
            requester_type text not null,
            requester_id text not null,
            approver_id text not null,
            subject_type text,
            subject_id text,
            status text not null,
            requested_at text not null,
            decided_at text,
            decided_by_type text,
            decided_by_id text,
            decision_reason text
        );

        create index if not exists idx_approvals_status
            on approvals (status, requested_at);

        create index if not exists idx_approvals_approver
            on approvals (approver_id, status, requested_at);

        create table if not exists agent_inbox (
            id text primary key,
            recipient_id text not null,
            item_type text not null,
            title text not null,
            body text not null,
            status text not null,
            source_type text,
            source_id text,
            created_at text not null,
            updated_at text not null
        );

        create index if not exists idx_agent_inbox_recipient
            on agent_inbox (recipient_id, status, updated_at);

        create index if not exists idx_agent_inbox_source
            on agent_inbox (source_type, source_id);
        """,
    ),
    Migration(
        version=5,
        name="create_comments_and_mentions",
        sql="""
        create table if not exists comments (
            id text primary key,
            task_id text not null,
            author_type text not null,
            author_id text not null,
            body text not null,
            created_at text not null
        );

        create index if not exists idx_comments_task
            on comments (task_id, created_at);

        create table if not exists comment_mentions (
            id text primary key,
            comment_id text not null,
            recipient_id text not null,
            status text not null,
            created_at text not null,
            resolved_at text,
            foreign key (comment_id) references comments (id) on delete cascade
        );

        create index if not exists idx_comment_mentions_recipient
            on comment_mentions (recipient_id, status, created_at);

        create index if not exists idx_comment_mentions_comment
            on comment_mentions (comment_id);
        """,
    ),
    Migration(
        version=6,
        name="create_runs",
        sql="""
        create table if not exists runs (
            id text primary key,
            task_id text not null,
            agent_id text not null,
            status text not null,
            artifact_dir_path text,
            created_at text not null,
            updated_at text not null
        );

        create index if not exists idx_runs_task
            on runs (task_id, created_at);

        create index if not exists idx_runs_agent
            on runs (agent_id, status, updated_at);

        create index if not exists idx_runs_status
            on runs (status, updated_at);
        """,
    ),
    Migration(
        version=7,
        name="add_task_parent",
        sql="""
        alter table tasks add column parent_task_id text references tasks(id);

        create index if not exists idx_tasks_parent
            on tasks (parent_task_id, updated_at);
        """,
    ),
)


def connect(path: Path) -> SQLiteConnection:
    """Open a SQLite connection for the runtime database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


def initialize(path: Path) -> None:
    """Create or migrate the runtime database."""
    with connect(path) as connection:
        _ensure_schema_migrations(connection)
        _apply_pending_migrations(connection)


def insert_event(connection: SQLiteConnection, event: Event) -> None:
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


def get_next_sequential_id(
    connection: SQLiteConnection,
    counter_name: str,
    prefix: str,
    width: int = 4,
) -> str:
    """Return the next formatted id from a SQLite-backed counter."""
    if not counter_name.strip():
        raise ValueError("counter_name must be a non-empty string.")

    row = connection.execute(
        "select next_value from id_counters where name = ?",
        (counter_name,),
    ).fetchone()
    if row is None:
        next_value = 1
        connection.execute(
            "insert into id_counters (name, next_value) values (?, ?)",
            (counter_name, 2),
        )
    else:
        next_value = int(row["next_value"])
        connection.execute(
            "update id_counters set next_value = ? where name = ?",
            (next_value + 1, counter_name),
        )

    return format_sequential_id(prefix, next_value, width=width)


def get_applied_migration_versions(connection: SQLiteConnection) -> set[int]:
    """Return applied migration versions."""
    _ensure_schema_migrations(connection)
    rows = connection.execute("select version from schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def get_expected_migration_versions() -> set[int]:
    """Return migration versions supported by this adapter."""
    return {migration.version for migration in MIGRATIONS}


def _ensure_schema_migrations(connection: SQLiteConnection) -> None:
    connection.execute(
        """
        create table if not exists schema_migrations (
            version integer primary key,
            name text not null,
            applied_at text not null
        )
        """
    )


def _apply_pending_migrations(connection: SQLiteConnection) -> None:
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
