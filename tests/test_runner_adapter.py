import sys
from pathlib import Path

import pytest
import yaml

from asynq_team_core.database import initialize_database
from asynq_team_core.paths import create_project_directories, get_project_layout
from asynq_team_core.project_files import seed_default_project_files
from asynq_team_core.run_task import start_task_run
from asynq_team_core.runner_adapter import (
    execute_run_adapter_command,
    plan_run_adapter_command,
)
from asynq_team_core.task_service import create_task_with_brief


def test_plan_run_adapter_command_renders_allowed_placeholders(tmp_path: Path) -> None:
    layout, started = _create_started_run(tmp_path)
    _replace_codex_command_template(
        layout,
        [
            sys.executable,
            "-c",
            "print('ok')",
            "{model}",
            "{work_packet}",
            "{run_id}",
            "{task_id}",
            "{agent_id}",
            "{workspace}",
        ],
    )

    plan = plan_run_adapter_command(
        layout=layout,
        run=started.work_packet.run,
        work_packet_path=started.work_packet.artifact.relative_path,
    )

    assert plan.runner_id == "codex"
    assert plan.tool == "codex.runner"
    assert plan.command == (
        sys.executable,
        "-c",
        "print('ok')",
        "gpt-5-codex",
        ".team/runs/george/RUN-0001/work.md",
        "RUN-0001",
        "TASK-0001",
        "george",
        layout.workspace.as_posix(),
    )
    assert plan.cwd == "."


def test_execute_run_adapter_command_runs_configured_command(tmp_path: Path) -> None:
    layout, started = _create_started_run(tmp_path)
    _replace_codex_command_template(
        layout,
        [
            sys.executable,
            "-c",
            "import pathlib, sys; print(pathlib.Path(sys.argv[1]).read_text()[:12])",
            "{work_packet}",
        ],
    )

    result = execute_run_adapter_command(
        database_path=layout.database_path,
        layout=layout,
        run=started.work_packet.run,
        work_packet_path=started.work_packet.artifact.relative_path,
        actor_type="agent",
        actor_id="george",
        timeout_seconds=5,
    )

    assert result.exit_code == 0
    assert result.stdout == "# Run RUN-00\n"
    assert result.record.event.payload["tool"] == "codex.runner"


def test_plan_run_adapter_command_rejects_unknown_placeholder(tmp_path: Path) -> None:
    layout, started = _create_started_run(tmp_path)
    _replace_codex_command_template(layout, ["echo", "{unknown}"])

    with pytest.raises(ValueError, match="Unknown runner command template placeholder: unknown"):
        plan_run_adapter_command(
            layout=layout,
            run=started.work_packet.run,
            work_packet_path=started.work_packet.artifact.relative_path,
        )


def _create_started_run(tmp_path: Path):
    layout = get_project_layout(tmp_path)
    create_project_directories(layout)
    seed_default_project_files(layout)
    initialize_database(layout.database_path)
    create_task_with_brief(
        database_path=layout.database_path,
        layout=layout,
        title="First task",
        brief_md="Build the first task.",
        actor_type="human",
        actor_id="founder",
        assignee_id="george",
    )
    started = start_task_run(
        database_path=layout.database_path,
        layout=layout,
        task_id="TASK-0001",
        agent_id="george",
        actor_type="agent",
        actor_id="george",
    )

    return layout, started


def _replace_codex_command_template(layout, command_template: list[str]) -> None:
    path = layout.policy_dir / "runners.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["runners"]["codex"]["command_template"] = command_template
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
