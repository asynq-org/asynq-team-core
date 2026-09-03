from pathlib import Path

import pytest

from asynq_team_core.database import initialize_database
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.run_work import prepare_run_work_packet
from asynq_team_core.runs import RunStatus
from asynq_team_core.task_service import create_task_with_brief


def test_prepare_run_work_packet_writes_context_and_updates_status(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    packet = prepare_run_work_packet(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        actor_type="agent",
        actor_id="george",
    )

    assert packet.run.status is RunStatus.WORKING
    assert packet.artifact.relative_path == ".team/runs/george/RUN-0001/work.md"
    assert packet.artifact.path.is_file()
    body = packet.artifact.path.read_text(encoding="utf-8")
    assert "# Run RUN-0001 Work Packet" in body
    assert "- Title: First task" in body
    assert "Build the first task." in body
    assert "### .team/rules/engineering.md" in body


def test_prepare_run_work_packet_preserves_existing_packet_by_default(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)
    prepare_run_work_packet(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        actor_type="agent",
        actor_id="george",
    )

    with pytest.raises(ValueError, match="Run work packet already exists"):
        prepare_run_work_packet(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            actor_type="agent",
            actor_id="george",
        )


def test_prepare_run_work_packet_can_overwrite_existing_packet(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)
    prepare_run_work_packet(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        actor_type="agent",
        actor_id="george",
    )

    packet = prepare_run_work_packet(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        actor_type="agent",
        actor_id="george",
        overwrite=True,
    )

    assert packet.artifact.path.read_text(encoding="utf-8").startswith("# Run RUN-0001")


def test_prepare_run_work_packet_rejects_rule_paths_outside_rules_dir(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)
    (layout.agents_dir / "george.yaml").write_text(
        "id: george\nrule_refs:\n  - ../policy/approvals.yaml\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Path escapes parent directory"):
        prepare_run_work_packet(
            database_path=layout.database_path,
            layout=layout,
            run_id=run_id,
            actor_type="agent",
            actor_id="george",
        )


def _create_workspace_run(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)
    task = create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
    ).task
    run = create_run_with_artifact_dir(
        database_path=layout.database_path,
        layout=layout,
        task_id=task.id,
        agent_id="george",
        actor_type="human",
        actor_id="founder",
    ).run

    return layout, run.id
