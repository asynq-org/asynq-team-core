from pathlib import Path

import pytest
import yaml

from asynq_team_core.approvals import list_approvals
from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.paths import ProjectLayout, create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.run_work import prepare_authorized_run_work_packet, prepare_run_work_packet
from asynq_team_core.runs import RunStatus, get_run
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
    assert "- Runner: codex" in body
    assert "- Model: gpt-5-codex" in body
    assert "- Max run budget USD: 5" in body
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
        """id: george
display_name: George
role: engineer
mission: Build implementation changes.
runner:
  default: codex
  default_model: gpt-5-codex
  allowed_models:
    - gpt-5-codex
  can_request_model_change: true
rule_refs:
  - ../policy/approvals.yaml
""",
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


def test_prepare_authorized_run_work_packet_allows_default_engineer(tmp_path: Path) -> None:
    layout, run_id = _create_workspace_run(tmp_path)

    result = prepare_authorized_run_work_packet(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        actor_type="agent",
        actor_id="george",
    )

    assert result.authorization is not None
    assert result.authorization.approval_request is None
    assert result.packet is not None
    assert result.packet.run.status is RunStatus.WORKING


def test_prepare_authorized_run_work_packet_requests_artifact_approval_when_gated(
    tmp_path: Path,
) -> None:
    layout, run_id = _create_workspace_run(tmp_path)
    _replace_role_artifact_create_policy(layout, "engineer", "require_approval")

    result = prepare_authorized_run_work_packet(
        database_path=layout.database_path,
        layout=layout,
        run_id=run_id,
        actor_type="agent",
        actor_id="george",
    )

    with connect_database(layout.database_path) as connection:
        stored_run = get_run(connection, run_id)
        approvals = list_approvals(connection)

    assert result.authorization is not None
    assert result.authorization.evaluation.capability == "artifact.create"
    assert result.authorization.approval_request is not None
    assert result.packet is None
    assert stored_run is not None
    assert stored_run.status is RunStatus.CREATED
    assert approvals == [result.authorization.approval_request.approval]
    assert not (layout.runs_dir / "george" / run_id / "work.md").exists()


def test_prepare_authorized_run_work_packet_rejects_denied_artifact_capability(
    tmp_path: Path,
) -> None:
    layout, run_id = _create_workspace_run(tmp_path)
    _replace_role_artifact_create_policy(layout, "engineer", "deny")

    with pytest.raises(PermissionError, match="denied for role"):
        prepare_authorized_run_work_packet(
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


def _replace_role_artifact_create_policy(layout: ProjectLayout, role: str, target: str) -> None:
    path = layout.policy_dir / "capabilities.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    role_policy = data["roles"][role]
    for field in ("allow", "require_approval", "deny"):
        role_policy[field] = [item for item in role_policy.get(field, []) if item != "artifact.create"]
    role_policy.setdefault(target, []).append("artifact.create")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
