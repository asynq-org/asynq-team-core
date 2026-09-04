from pathlib import Path

import yaml

from asynq_team_core.database import connect_database, initialize_database
from asynq_team_core.doctor import DoctorStatus, run_doctor
from asynq_team_core.paths import get_project_layout
from asynq_team_core.project import initialize_project


def test_run_doctor_reports_initialized_workspace(tmp_path: Path) -> None:
    initialization = initialize_project(tmp_path)
    initialize_database(initialization.layout.database_path)

    report = run_doctor(initialization.layout)
    checks = _checks_by_name(report)

    assert report.has_failures is False
    assert checks["workspace"].status is DoctorStatus.PASS
    assert checks["config"].status is DoctorStatus.PASS
    assert checks["database"].status is DoctorStatus.PASS
    assert checks["migrations"].status is DoctorStatus.PASS
    assert checks["default_files"].status is DoctorStatus.PASS
    assert checks["runner_policy"].status is DoctorStatus.PASS
    assert checks["git_backup"].status is DoctorStatus.WARN


def test_run_doctor_accepts_configured_git_backup_remote(tmp_path: Path) -> None:
    initialization = initialize_project(
        tmp_path,
        git_remote="git@github.com:example/team-state.git",
    )
    initialize_database(initialization.layout.database_path)

    report = run_doctor(initialization.layout)
    checks = _checks_by_name(report)

    assert report.has_failures is False
    assert checks["git_backup"].status is DoctorStatus.PASS


def test_run_doctor_reports_missing_workspace_state(tmp_path: Path) -> None:
    layout = get_project_layout(tmp_path)

    report = run_doctor(layout)
    checks = _checks_by_name(report)

    assert report.has_failures is True
    assert checks["team_dir"].status is DoctorStatus.FAIL
    assert checks["config"].status is DoctorStatus.FAIL
    assert checks["database"].status is DoctorStatus.FAIL


def test_run_doctor_reports_missing_migrations(tmp_path: Path) -> None:
    initialization = initialize_project(tmp_path)
    with connect_database(initialization.layout.database_path) as connection:
        connection.execute(
            """
            create table schema_migrations (
                version integer primary key,
                name text not null,
                applied_at text not null
            )
            """
        )

    report = run_doctor(initialization.layout)
    checks = _checks_by_name(report)

    assert report.has_failures is True
    assert checks["migrations"].status is DoctorStatus.FAIL
    assert "Missing database migrations" in checks["migrations"].message


def test_run_doctor_reports_invalid_runner_policy(tmp_path: Path) -> None:
    initialization = initialize_project(tmp_path)
    initialize_database(initialization.layout.database_path)
    path = initialization.layout.policy_dir / "runners.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["allowed_tools"] = "shell.read"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    report = run_doctor(initialization.layout)
    checks = _checks_by_name(report)

    assert report.has_failures is True
    assert checks["runner_policy"].status is DoctorStatus.FAIL
    assert "Runner policy is invalid" in checks["runner_policy"].message


def _checks_by_name(report) -> dict:
    return {check.name: check for check in report.checks}
