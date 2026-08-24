"""Append-only runtime event helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def format_event_time(value: datetime) -> str:
    """Format an event timestamp as an ISO-8601 UTC string."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def new_event_id() -> str:
    """Return a new local event id."""
    return f"EVT-{uuid.uuid4().hex}"


@dataclass(frozen=True)
class Event:
    """Structured runtime event with a tamper-evident hash."""

    id: str
    type: str
    entity_type: str
    entity_id: str
    actor_type: str
    actor_id: str
    payload: dict[str, Any]
    created_at: str
    prev_hash: str | None
    hash: str

    def to_record(self) -> dict[str, Any]:
        """Return a persistence-friendly event record."""
        return {
            "id": self.id,
            "type": self.type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "payload_json": json.dumps(self.payload, sort_keys=True, separators=(",", ":")),
            "created_at": self.created_at,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


def create_event(
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any],
    prev_hash: str | None = None,
    event_id: str | None = None,
    clock: Clock = utc_now,
) -> Event:
    """Create a structured event and calculate its hash."""
    event_id = event_id or new_event_id()
    created_at = format_event_time(clock())
    event_hash = calculate_event_hash(
        event_id=event_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        actor_id=actor_id,
        payload=payload,
        created_at=created_at,
        prev_hash=prev_hash,
    )

    return Event(
        id=event_id,
        type=_require_non_empty(event_type, "event_type"),
        entity_type=_require_non_empty(entity_type, "entity_type"),
        entity_id=_require_non_empty(entity_id, "entity_id"),
        actor_type=_require_non_empty(actor_type, "actor_type"),
        actor_id=_require_non_empty(actor_id, "actor_id"),
        payload=payload,
        created_at=created_at,
        prev_hash=prev_hash,
        hash=event_hash,
    )


def calculate_event_hash(
    event_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any],
    created_at: str,
    prev_hash: str | None,
) -> str:
    """Return a deterministic SHA-256 hash for an event record."""
    hash_input = {
        "id": _require_non_empty(event_id, "event_id"),
        "type": _require_non_empty(event_type, "event_type"),
        "entity_type": _require_non_empty(entity_type, "entity_type"),
        "entity_id": _require_non_empty(entity_id, "entity_id"),
        "actor_type": _require_non_empty(actor_type, "actor_type"),
        "actor_id": _require_non_empty(actor_id, "actor_id"),
        "payload": payload,
        "created_at": _require_non_empty(created_at, "created_at"),
        "prev_hash": prev_hash,
    }
    encoded = json.dumps(hash_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value
