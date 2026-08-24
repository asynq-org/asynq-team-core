"""Identifier helpers for local runtime entities."""

import re

ID_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*$")


def format_sequential_id(prefix: str, value: int, width: int = 4) -> str:
    """Format a stable local id such as TASK-0001."""
    if not ID_PREFIX_PATTERN.match(prefix):
        raise ValueError("ID prefix must contain only uppercase letters and digits.")
    if value < 1:
        raise ValueError("ID value must be a positive integer.")
    if width < 1:
        raise ValueError("ID width must be a positive integer.")

    return f"{prefix}-{value:0{width}d}"
