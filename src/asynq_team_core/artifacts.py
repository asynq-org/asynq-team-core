"""Markdown artifact writers for project-local runtime state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.paths import ProjectLayout

TASK_ID_PATTERN = re.compile(r"^TASK-[0-9]{4,}$")


@dataclass(frozen=True)
class ArtifactWrite:
    """Result of writing a project-local artifact."""

    path: Path
    relative_path: str


def write_task_brief(
    layout: ProjectLayout,
    task_id: str,
    body_md: str,
    overwrite: bool = False,
) -> ArtifactWrite:
    """Write a task brief artifact for a task."""
    clean_task_id = _validate_task_id(task_id)
    task_dir = layout.tasks_dir / clean_task_id
    artifact_path = task_dir / "brief.md"

    _ensure_child_path(layout.tasks_dir, artifact_path)
    task_dir.mkdir(parents=True, exist_ok=True)

    mode = "w" if overwrite else "x"
    with artifact_path.open(mode, encoding="utf-8") as artifact_file:
        artifact_file.write(body_md)
        if body_md and not body_md.endswith("\n"):
            artifact_file.write("\n")

    return ArtifactWrite(
        path=artifact_path,
        relative_path=artifact_path.relative_to(layout.workspace).as_posix(),
    )


def _validate_task_id(task_id: str) -> str:
    if not TASK_ID_PATTERN.match(task_id):
        raise ValueError("task_id must use TASK-0001 format.")
    return task_id


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes parent directory: {child}") from exc
