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


def write_run_work_packet(
    layout: ProjectLayout,
    artifact_dir_path: str,
    body_md: str,
    overwrite: bool = False,
) -> ArtifactWrite:
    """Write the initial work packet for a run."""
    return _write_run_artifact(
        layout=layout,
        artifact_dir_path=artifact_dir_path,
        file_name="work.md",
        body_md=body_md,
        label="Run work packet",
        overwrite=overwrite,
    )


def write_run_result(
    layout: ProjectLayout,
    artifact_dir_path: str,
    body_md: str,
    overwrite: bool = False,
) -> ArtifactWrite:
    """Write the review result artifact for a run."""
    return _write_run_artifact(
        layout=layout,
        artifact_dir_path=artifact_dir_path,
        file_name="result.md",
        body_md=body_md,
        label="Run result",
        overwrite=overwrite,
    )


def write_run_review(
    layout: ProjectLayout,
    artifact_dir_path: str,
    body_md: str,
    overwrite: bool = False,
) -> ArtifactWrite:
    """Write the supervisor review artifact for a run."""
    return _write_run_artifact(
        layout=layout,
        artifact_dir_path=artifact_dir_path,
        file_name="review.md",
        body_md=body_md,
        label="Run review",
        overwrite=overwrite,
    )


def _write_run_artifact(
    layout: ProjectLayout,
    artifact_dir_path: str,
    file_name: str,
    body_md: str,
    label: str,
    overwrite: bool,
) -> ArtifactWrite:
    artifact_dir = _resolve_run_artifact_dir(layout, artifact_dir_path)
    artifact_path = artifact_dir / file_name

    _ensure_child_path(layout.runs_dir, artifact_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    mode = "w" if overwrite else "x"
    try:
        with artifact_path.open(mode, encoding="utf-8") as artifact_file:
            artifact_file.write(body_md)
            if body_md and not body_md.endswith("\n"):
                artifact_file.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"{label} already exists: {artifact_path}") from exc

    return ArtifactWrite(
        path=artifact_path,
        relative_path=artifact_path.relative_to(layout.workspace).as_posix(),
    )


def _validate_task_id(task_id: str) -> str:
    if not TASK_ID_PATTERN.match(task_id):
        raise ValueError("task_id must use TASK-0001 format.")
    return task_id


def _resolve_run_artifact_dir(layout: ProjectLayout, artifact_dir_path: str) -> Path:
    if not artifact_dir_path or not artifact_dir_path.strip():
        raise ValueError("artifact_dir_path must be a non-empty string.")

    artifact_dir = layout.workspace / artifact_dir_path
    _ensure_child_path(layout.runs_dir, artifact_dir)
    return artifact_dir


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes parent directory: {child}") from exc
