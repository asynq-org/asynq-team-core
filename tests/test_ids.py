import pytest

from asynq_team_core.ids import format_sequential_id


def test_format_sequential_id_uses_prefix_and_zero_padding() -> None:
    assert format_sequential_id("TASK", 7) == "TASK-0007"


def test_format_sequential_id_rejects_invalid_prefix() -> None:
    with pytest.raises(ValueError, match="prefix"):
        format_sequential_id("task", 1)


def test_format_sequential_id_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        format_sequential_id("TASK", 0)
