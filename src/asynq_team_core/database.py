"""Database adapter facade for the current local-first runtime."""

from pathlib import Path

from asynq_team_core.adapters import sqlite
from asynq_team_core.events import Event

DatabaseConnection = sqlite.SQLiteConnection
DatabaseRow = sqlite.SQLiteRow


def connect_database(path: Path) -> DatabaseConnection:
    """Open a connection using the configured MVP database adapter."""
    return sqlite.connect(path)


def initialize_database(path: Path) -> None:
    """Create or migrate the runtime database using the configured adapter."""
    sqlite.initialize(path)


def insert_event(connection: DatabaseConnection, event: Event) -> None:
    """Persist an event record using the configured adapter."""
    sqlite.insert_event(connection, event)


def get_next_sequential_id(
    connection: DatabaseConnection,
    counter_name: str,
    prefix: str,
    width: int = 4,
) -> str:
    """Return the next formatted id using the configured adapter."""
    return sqlite.get_next_sequential_id(connection, counter_name, prefix, width=width)


def get_applied_migration_versions(connection: DatabaseConnection) -> set[int]:
    """Return applied migration versions using the configured adapter."""
    return sqlite.get_applied_migration_versions(connection)
