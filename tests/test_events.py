from datetime import datetime, timezone

import pytest

from asynq_team_core.events import calculate_event_hash, create_event, format_event_time


def test_format_event_time_uses_utc_suffix() -> None:
    value = datetime(2026, 8, 23, 12, 30, 0, tzinfo=timezone.utc)

    assert format_event_time(value) == "2026-08-23T12:30:00Z"


def test_create_event_calculates_deterministic_hash() -> None:
    event = create_event(
        event_type="task.created",
        entity_type="task",
        entity_id="TASK-0001",
        actor_type="human",
        actor_id="founder",
        payload={"title": "First task"},
        prev_hash="previous",
        event_id="EVT-0001",
        clock=lambda: datetime(2026, 8, 23, 12, 30, 0, tzinfo=timezone.utc),
    )

    assert event.hash == calculate_event_hash(
        event_id="EVT-0001",
        event_type="task.created",
        entity_type="task",
        entity_id="TASK-0001",
        actor_type="human",
        actor_id="founder",
        payload={"title": "First task"},
        created_at="2026-08-23T12:30:00Z",
        prev_hash="previous",
    )


def test_event_record_serializes_payload_as_canonical_json() -> None:
    event = create_event(
        event_type="task.created",
        entity_type="task",
        entity_id="TASK-0001",
        actor_type="human",
        actor_id="founder",
        payload={"b": 2, "a": 1},
        event_id="EVT-0001",
        clock=lambda: datetime(2026, 8, 23, 12, 30, 0, tzinfo=timezone.utc),
    )

    assert event.to_record()["payload_json"] == '{"a":1,"b":2}'


def test_create_event_rejects_empty_required_strings() -> None:
    with pytest.raises(ValueError, match="event_type"):
        create_event(
            event_type="",
            entity_type="task",
            entity_id="TASK-0001",
            actor_type="human",
            actor_id="founder",
            payload={},
        )
