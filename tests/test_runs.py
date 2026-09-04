from datetime import UTC, datetime
from pathlib import Path

import pytest

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.runs import (
    RunStatus,
    create_run,
    get_next_agent_run,
    get_run,
    list_runs,
    update_run_status,
)
from asynq_team_core.tasks import create_task


def test_create_run_persists_run_and_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        run = create_run(
            connection,
            task_id=task.id,
            agent_id="george",
            actor_type="human",
            actor_id="founder",
            artifact_dir_path=".team/runs/george/RUN-0001",
            runner_id="codex",
            model="gpt-5-codex",
            clock=lambda: datetime(2026, 9, 2, 12, 30, 0, tzinfo=UTC),
        )
        loaded = get_run(connection, run.id)
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("run.created", run.id),
        ).fetchone()

    assert run.id == "RUN-0001"
    assert run.status is RunStatus.CREATED
    assert run.runner_id == "codex"
    assert run.model == "gpt-5-codex"
    assert loaded == run
    assert event is not None


def test_create_run_rejects_missing_task(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="Task not found: TASK-9999"),
    ):
        create_run(
            connection,
            task_id="TASK-9999",
            agent_id="george",
            actor_type="human",
            actor_id="founder",
        )


def test_list_runs_filters_by_task_agent_and_status(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        first_task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        second_task = create_task(
            connection,
            title="Second task",
            actor_type="human",
            actor_id="founder",
        )
        run = create_run(
            connection,
            task_id=first_task.id,
            agent_id="george",
            actor_type="human",
            actor_id="founder",
        )
        create_run(
            connection,
            task_id=second_task.id,
            agent_id="ea",
            actor_type="human",
            actor_id="founder",
        )

        runs = list_runs(
            connection,
            task_id=first_task.id,
            agent_id="george",
            status=RunStatus.CREATED,
        )

    assert runs == [run]


def test_get_next_agent_run_returns_oldest_actionable_run(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        first_task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        second_task = create_task(
            connection,
            title="Second task",
            actor_type="human",
            actor_id="founder",
        )
        create_task(
            connection,
            title="Other agent task",
            actor_type="human",
            actor_id="founder",
        )
        completed_run = create_run(
            connection,
            task_id=first_task.id,
            agent_id="george",
            actor_type="human",
            actor_id="founder",
        )
        expected_run = create_run(
            connection,
            task_id=second_task.id,
            agent_id="george",
            actor_type="human",
            actor_id="founder",
        )
        create_run(
            connection,
            task_id=first_task.id,
            agent_id="ea",
            actor_type="human",
            actor_id="founder",
        )
        update_run_status(
            connection,
            completed_run.id,
            RunStatus.COMPLETED,
            actor_type="agent",
            actor_id="george",
        )

        next_run = get_next_agent_run(connection, "george")

    assert next_run == expected_run


def test_get_next_agent_run_returns_none_without_actionable_runs(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        assert get_next_agent_run(connection, "george") is None


def test_update_run_status_records_event(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        task = create_task(
            connection,
            title="First task",
            actor_type="human",
            actor_id="founder",
        )
        run = create_run(
            connection,
            task_id=task.id,
            agent_id="george",
            actor_type="human",
            actor_id="founder",
        )
        updated = update_run_status(
            connection,
            run.id,
            RunStatus.PLANNING,
            actor_type="agent",
            actor_id="george",
        )
        event = connection.execute(
            "select * from events where type = ? and entity_id = ?",
            ("run.status_changed", run.id),
        ).fetchone()

    assert updated.status is RunStatus.PLANNING
    assert event is not None


def test_update_run_status_rejects_missing_run(tmp_path: Path) -> None:
    database_path = tmp_path / "team.db"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ValueError, match="Run not found: RUN-9999"),
    ):
        update_run_status(
            connection,
            "RUN-9999",
            RunStatus.PLANNING,
            actor_type="agent",
            actor_id="george",
        )
