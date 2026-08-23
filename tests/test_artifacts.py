from pathlib import Path

import pytest

from asynq_team_core.artifacts import write_task_brief
from asynq_team_core.paths import create_project_directories, get_project_layout


def test_write_task_brief_creates_markdown_artifact(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)

    artifact = write_task_brief(layout, "TASK-0001", "Build the task ledger.")

    assert artifact.relative_path == ".team/tasks/TASK-0001/brief.md"
    assert artifact.path.read_text(encoding="utf-8") == "Build the task ledger.\n"


def test_write_task_brief_rejects_invalid_task_id(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)

    with pytest.raises(ValueError, match="TASK-0001"):
        write_task_brief(layout, "../TASK-0001", "Invalid")


def test_write_task_brief_does_not_overwrite_by_default(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    write_task_brief(layout, "TASK-0001", "Original")

    with pytest.raises(FileExistsError):
        write_task_brief(layout, "TASK-0001", "Replacement")


def test_write_task_brief_can_overwrite_when_requested(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    write_task_brief(layout, "TASK-0001", "Original")

    artifact = write_task_brief(layout, "TASK-0001", "Replacement", overwrite=True)

    assert artifact.path.read_text(encoding="utf-8") == "Replacement\n"
