"""Run work packet preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asynq_team_core.artifacts import ArtifactWrite, write_run_work_packet
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.runs import Run, RunStatus, get_run, update_run_status
from asynq_team_core.tasks import Task, get_task

WORK_STARTABLE_STATUSES = frozenset(
    {
        RunStatus.CREATED,
        RunStatus.CLAIMED,
        RunStatus.PLANNING,
        RunStatus.WORKING,
        RunStatus.RETURNED,
    }
)


@dataclass(frozen=True)
class TextDocument:
    """A project-local text document included in a work packet."""

    relative_path: str
    body: str


@dataclass(frozen=True)
class RunWorkPacket:
    """Prepared context and artifact for starting local run work."""

    run: Run
    task: Task
    artifact: ArtifactWrite
    brief: TextDocument | None
    agent_manifest: TextDocument | None
    rules: tuple[TextDocument, ...]


def prepare_run_work_packet(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    actor_type: str,
    actor_id: str,
    overwrite: bool = False,
    clock: Clock = utc_now,
) -> RunWorkPacket:
    """Prepare a reviewable work packet artifact for a run."""
    with connect_database(database_path) as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        if run.artifact_dir_path is None:
            raise ValueError(f"Run has no artifact directory: {run.id}")
        if run.status not in WORK_STARTABLE_STATUSES:
            raise ValueError(f"Run cannot be worked from status: {run.status.value}")

        task = get_task(connection, run.task_id)
        if task is None:
            raise ValueError(f"Task not found for run {run.id}: {run.task_id}")

    brief = _read_optional_workspace_file(layout, task.brief_artifact_path)
    agent_manifest = _read_agent_manifest(layout, run.agent_id)
    rule_refs = _extract_rule_refs(agent_manifest.body if agent_manifest else "")
    rules = tuple(_read_rule_file(layout, rule_ref) for rule_ref in rule_refs)
    body = _render_work_packet(run, task, brief, agent_manifest, rules)
    artifact = write_run_work_packet(
        layout=layout,
        artifact_dir_path=run.artifact_dir_path,
        body_md=body,
        overwrite=overwrite,
    )

    with connect_database(database_path) as connection:
        updated_run = update_run_status(
            connection,
            run_id=run.id,
            status=RunStatus.WORKING,
            actor_type=actor_type,
            actor_id=actor_id,
            clock=clock,
        )

    return RunWorkPacket(
        run=updated_run,
        task=task,
        artifact=artifact,
        brief=brief,
        agent_manifest=agent_manifest,
        rules=rules,
    )


def _read_optional_workspace_file(
    layout: ProjectLayout,
    relative_path: str | None,
) -> TextDocument | None:
    if relative_path is None:
        return None

    path = layout.workspace / relative_path
    _ensure_child_path(layout.workspace, path)
    if not path.is_file():
        return None

    return TextDocument(
        relative_path=path.relative_to(layout.workspace).as_posix(),
        body=path.read_text(encoding="utf-8"),
    )


def _read_agent_manifest(layout: ProjectLayout, agent_id: str) -> TextDocument | None:
    path = layout.agents_dir / f"{agent_id}.yaml"
    _ensure_child_path(layout.agents_dir, path)
    if not path.is_file():
        return None

    return TextDocument(
        relative_path=path.relative_to(layout.workspace).as_posix(),
        body=path.read_text(encoding="utf-8"),
    )


def _extract_rule_refs(manifest_body: str) -> tuple[str, ...]:
    if not manifest_body:
        return ()

    yaml = _require_yaml()
    data = yaml.safe_load(manifest_body) or {}
    if not isinstance(data, dict):
        raise TypeError("Agent manifest root must be a mapping.")

    rule_refs = data.get("rule_refs", ())
    if rule_refs is None:
        return ()
    if not isinstance(rule_refs, list):
        raise TypeError("Agent manifest rule_refs must be a list.")

    refs: list[str] = []
    for rule_ref in rule_refs:
        if not isinstance(rule_ref, str) or not rule_ref.strip():
            raise ValueError("Agent manifest rule_refs must contain non-empty strings.")
        refs.append(rule_ref.strip())

    return tuple(refs)


def _read_rule_file(layout: ProjectLayout, rule_ref: str) -> TextDocument:
    path = layout.team_dir / rule_ref
    _ensure_child_path(layout.rules_dir, path)
    if not path.is_file():
        raise ValueError(f"Rule file not found: {rule_ref}")

    return TextDocument(
        relative_path=path.relative_to(layout.workspace).as_posix(),
        body=path.read_text(encoding="utf-8"),
    )


def _render_work_packet(
    run: Run,
    task: Task,
    brief: TextDocument | None,
    agent_manifest: TextDocument | None,
    rules: tuple[TextDocument, ...],
) -> str:
    sections = [
        f"# Run {run.id} Work Packet",
        "",
        "## Run",
        f"- Task: {run.task_id}",
        f"- Agent: {run.agent_id}",
        f"- Status: {run.status.value}",
        "",
        "## Task",
        f"- ID: {task.id}",
        f"- Title: {task.title}",
        f"- Priority: {task.priority}",
        f"- Status: {task.status.value}",
    ]

    if task.assignee_id:
        sections.append(f"- Assignee: {task.assignee_id}")

    sections.extend(
        [
            "",
            "## Brief",
            brief.body.rstrip() if brief else "_No task brief artifact found._",
            "",
            "## Agent Manifest",
            f"`{agent_manifest.relative_path}`" if agent_manifest else "_No agent manifest found._",
            "",
            "## Rules",
        ]
    )

    if rules:
        for rule in rules:
            sections.extend(["", f"### {rule.relative_path}", rule.body.rstrip()])
    else:
        sections.append("_No rule files were loaded._")

    sections.extend(
        [
            "",
            "## Work Checklist",
            "- Confirm the task brief and applicable rules before making changes.",
            "- Keep changes small, reviewable, and audit-friendly.",
            "- Record blockers, assumptions, and follow-up tasks as comments or artifacts.",
            "- Run relevant local checks before proposing review or completion.",
        ]
    )

    return "\n".join(sections)


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Path escapes parent directory: {child}") from exc


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read Asynq Team agent manifests.") from exc

    return yaml
