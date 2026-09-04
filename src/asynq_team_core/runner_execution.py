"""Policy-enforced local runner command execution."""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.paths import ProjectLayout
from asynq_team_core.run_commands import RunCommandRecord, record_run_command
from asynq_team_core.runner_policy import RunnerToolDecision, evaluate_runner_tool

MAX_CAPTURED_OUTPUT_CHARS = 20_000
TIMEOUT_EXIT_CODE = 124


@dataclass(frozen=True)
class RunnerExecution:
    """Result of running a local command through runner policy enforcement."""

    record: RunCommandRecord
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int


def execute_run_command(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    tool: str,
    command: tuple[str, ...],
    actor_type: str,
    actor_id: str,
    cwd: str | None = None,
    timeout_seconds: int = 300,
) -> RunnerExecution:
    """Run a command after runner policy allows the requested tool."""
    evaluation = evaluate_runner_tool(layout, tool)
    if evaluation.decision is RunnerToolDecision.DENY:
        raise PermissionError(evaluation.reason)

    clean_command = _validate_command(command)
    clean_timeout_seconds = _require_positive_int(timeout_seconds, "timeout_seconds")
    execution_cwd = _resolve_execution_cwd(layout, cwd)
    started = time.monotonic()
    timed_out = False

    try:
        completed = subprocess.run(
            clean_command,
            cwd=execution_cwd,
            text=True,
            capture_output=True,
            timeout=clean_timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout = _truncate_output(completed.stdout)
        stderr = _truncate_output(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = TIMEOUT_EXIT_CODE
        stdout = _truncate_output(_decode_timeout_output(exc.stdout))
        stderr = _truncate_output(_decode_timeout_output(exc.stderr))

    duration_ms = int((time.monotonic() - started) * 1000)
    record = record_run_command(
        database_path=database_path,
        run_id=run_id,
        command=shlex.join(clean_command),
        exit_code=exit_code,
        cwd=execution_cwd.relative_to(layout.workspace).as_posix(),
        duration_ms=duration_ms,
        tool=tool,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return RunnerExecution(
        record=record,
        command=clean_command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_ms=duration_ms,
    )


def _validate_command(command: tuple[str, ...]) -> tuple[str, ...]:
    if not command:
        raise ValueError("command must not be empty.")

    clean_parts: list[str] = []
    for part in command:
        if not isinstance(part, str) or not part.strip():
            raise ValueError("command entries must be non-empty strings.")
        clean_parts.append(part)

    return tuple(clean_parts)


def _resolve_execution_cwd(layout: ProjectLayout, cwd: str | None) -> Path:
    if cwd is None:
        return layout.workspace.resolve(strict=False)
    if not isinstance(cwd, str) or not cwd.strip():
        raise ValueError("cwd must be a non-empty string.")

    path = Path(cwd.strip())
    if path.is_absolute():
        resolved = path.resolve(strict=False)
    else:
        resolved = (layout.workspace / path).resolve(strict=False)

    try:
        resolved.relative_to(layout.workspace.resolve(strict=False))
    except ValueError as exc:
        raise ValueError(f"cwd escapes the workspace: {cwd}") from exc

    return resolved


def _require_positive_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer.")
    if value < 1:
        raise ValueError(f"{field_name} must be positive.")
    return value


def _truncate_output(value: str) -> str:
    if len(value) <= MAX_CAPTURED_OUTPUT_CHARS:
        return value
    return value[:MAX_CAPTURED_OUTPUT_CHARS]


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
