"""Run work packet preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.agent_manifests import AgentManifest, load_agent_manifest
from asynq_team_core.artifact_policy import authorize_run_artifact_creation
from asynq_team_core.artifacts import ArtifactWrite, write_run_work_packet
from asynq_team_core.database import connect_database
from asynq_team_core.events import Clock, utc_now
from asynq_team_core.paths import ProjectLayout
from asynq_team_core.policy import CapabilityAuthorization
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
    parsed_agent_manifest: AgentManifest | None
    rules: tuple[TextDocument, ...]


@dataclass(frozen=True)
class AuthorizedRunWorkPacket:
    """Result of an authorized run work packet preparation attempt."""

    authorization: CapabilityAuthorization | None
    packet: RunWorkPacket | None


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
    run, task = _load_startable_run(database_path, run_id)
    brief = _read_optional_workspace_file(layout, task.brief_artifact_path)
    agent_manifest = _read_agent_manifest(layout, run.agent_id)
    parsed_agent_manifest = _load_optional_agent_manifest(layout, run.agent_id, agent_manifest)
    rule_refs = parsed_agent_manifest.rule_refs if parsed_agent_manifest else ()
    rules = tuple(_read_rule_file(layout, rule_ref) for rule_ref in rule_refs)
    body = _render_work_packet(run, task, brief, agent_manifest, parsed_agent_manifest, rules)
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
        parsed_agent_manifest=parsed_agent_manifest,
        rules=rules,
    )


def prepare_authorized_run_work_packet(
    database_path: Path,
    layout: ProjectLayout,
    run_id: str,
    actor_type: str,
    actor_id: str,
    overwrite: bool = False,
    approver_id: str = "founder",
    clock: Clock = utc_now,
) -> AuthorizedRunWorkPacket:
    """Prepare a run work packet after enforcing agent artifact.create capability."""
    run, _task = _load_startable_run(database_path, run_id)
    authorization = authorize_run_artifact_creation(
        database_path=database_path,
        layout=layout,
        run=run,
        actor_type=actor_type,
        actor_id=actor_id,
        approver_id=approver_id,
        clock=clock,
    )
    if authorization is not None and authorization.approval_request is not None:
        return AuthorizedRunWorkPacket(authorization=authorization, packet=None)

    packet = prepare_run_work_packet(
        database_path=database_path,
        layout=layout,
        run_id=run.id,
        actor_type=actor_type,
        actor_id=actor_id,
        overwrite=overwrite,
        clock=clock,
    )

    return AuthorizedRunWorkPacket(authorization=authorization, packet=packet)


def _load_startable_run(database_path: Path, run_id: str) -> tuple[Run, Task]:
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

    return run, task


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


def _load_optional_agent_manifest(
    layout: ProjectLayout,
    agent_id: str,
    agent_manifest: TextDocument | None,
) -> AgentManifest | None:
    if agent_manifest is None:
        return None
    return load_agent_manifest(layout, agent_id)


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
    parsed_agent_manifest: AgentManifest | None,
    rules: tuple[TextDocument, ...],
) -> str:
    sections = [
        f"# Run {run.id} Work Packet",
        "",
        "## Run",
        f"- Task: {run.task_id}",
        f"- Agent: {run.agent_id}",
        f"- Status: {run.status.value}",
    ]
    if parsed_agent_manifest is not None:
        sections.extend(
            [
                f"- Runner: {run.runner_id or parsed_agent_manifest.runner.default}",
                f"- Model: {run.model or parsed_agent_manifest.runner.default_model}",
            ]
        )
        if run.requested_model:
            sections.append(f"- Requested model: {run.requested_model}")
        if parsed_agent_manifest.runner.max_run_budget_usd is not None:
            sections.append(
                f"- Max run budget USD: {parsed_agent_manifest.runner.max_run_budget_usd:g}"
            )

    sections.extend(
        [
            "",
            "## Task",
            f"- ID: {task.id}",
            f"- Title: {task.title}",
            f"- Priority: {task.priority}",
            f"- Status: {task.status.value}",
        ]
    )

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
