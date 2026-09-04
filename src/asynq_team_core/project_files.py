"""Default project-local rule, policy, and agent files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asynq_team_core.paths import ProjectLayout


@dataclass(frozen=True)
class ProjectFileTemplate:
    """Template for a project-local file created by initialization."""

    relative_path: Path
    body: str


def default_project_files() -> tuple[ProjectFileTemplate, ...]:
    """Return default files that make a new workspace immediately usable."""
    return (
        ProjectFileTemplate(
            relative_path=Path("rules/company.md"),
            body="""# Company Rules

- Work local-first and CLI-first for MVP changes.
- Keep changes scoped, reviewable, and auditable.
- Create follow-up tasks for non-breaking improvements noticed during work.
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("rules/engineering.md"),
            body="""# Engineering Rules

- Write reusable code with small functions and clear inputs and outputs.
- Keep functions minimalist and focused on one coherent behavior.
- Use Poetry for Python packaging, dependency management, and lockfiles.
- Use known, maintained, security-conscious dependencies.
- Run relevant lint, tests, release metadata, and security checks before commits.
- Prefer frequent, small, isolated commits with coherent intent.
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("rules/security.md"),
            body="""# Security Rules

- Never store raw secrets in repository files, logs, prompts, or test fixtures.
- Validate external input at runtime boundaries.
- Require approvals for destructive, irreversible, external, expensive, or sensitive actions.
- Do not let agents grant permissions to themselves or weaken approval requirements.
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("policy/capabilities.yaml"),
            body="""version: 1
roles:
  ea:
    allow:
      - project.read
      - task.create
      - inbox.manage
      - comment.draft
      - approval.request
    require_approval:
      - external.write
    deny:
      - repo.write
      - secrets.read
      - policy.change
  engineer:
    allow:
      - project.read
      - repo.read
      - repo.write.branch
      - task.create
      - comment.create
      - artifact.create
      - check.run
      - approval.request
    require_approval:
      - main.merge
      - production.deploy
      - external.write
      - secrets.read
      - policy.change
    deny:
      - approval.bypass
  supervisor:
    allow:
      - project.read
      - repo.read
      - audit.read
      - review.create
      - comment.create
      - task.create
      - approval.request
    require_approval:
      - policy.change
    deny:
      - repo.write
      - main.merge
      - production.deploy
      - permission.self_grant
      - approval.bypass
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("policy/approvals.yaml"),
            body="""version: 1
required_for:
  - main.merge
  - production.deploy
  - external.write
  - secrets.read
  - destructive.file.change
  - destructive.database.change
  - paid_api.high_usage
  - policy.change
  - runner.allowlist.change
  - protected_paths.change
  - agent.permission.change
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("policy/protected-paths.yaml"),
            body="""version: 1
paths:
  - .team/policy/**
  - .team/agents/**
  - .team/rules/**
  - .github/workflows/**
  - pyproject.toml
  - poetry.lock
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("policy/runners.yaml"),
            body="""version: 1
allowed_tools:
  - shell.read
  - shell.test
  - git.read
  - git.write.branch
  - codex.runner
denied_tools:
  - shell.destructive
  - production.deploy
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("agents/ea.yaml"),
            body="""id: ea
display_name: EA
role: ea
mission: Manage intake, inbox hygiene, summaries, and approval requests.
rule_refs:
  - rules/company.md
  - rules/security.md
capabilities:
  - project.read
  - task.create
  - inbox.manage
  - comment.draft
  - approval.request
approvals:
  required_for:
    - external.write
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("agents/george.yaml"),
            body="""id: george
display_name: George
role: engineer
mission: Build implementation changes with tests and clear audit trails.
supervisor: supervisor
rule_refs:
  - rules/company.md
  - rules/engineering.md
  - rules/security.md
capabilities:
  - project.read
  - repo.read
  - repo.write.branch
  - task.create
  - comment.create
  - artifact.create
  - check.run
  - approval.request
approvals:
  required_for:
    - main.merge
    - production.deploy
    - external.write
    - secrets.read
    - policy.change
""",
        ),
        ProjectFileTemplate(
            relative_path=Path("agents/supervisor.yaml"),
            body="""id: supervisor
display_name: Supervisor
role: supervisor
mission: Review plans, diffs, risk, audit trails, and final recommendations.
rule_refs:
  - rules/company.md
  - rules/engineering.md
  - rules/security.md
capabilities:
  - project.read
  - repo.read
  - audit.read
  - review.create
  - task.create
  - approval.request
approvals:
  required_for:
    - policy.change
""",
        ),
    )


def seed_default_project_files(
    layout: ProjectLayout,
    overwrite: bool = False,
) -> tuple[Path, ...]:
    """Write default project files and preserve existing files by default."""
    created_files: list[Path] = []
    for template in default_project_files():
        target = layout.team_dir / template.relative_path
        _ensure_child_path(layout.team_dir, target)
        if _write_seed_file(target, template.body, overwrite=overwrite):
            created_files.append(target)

    return tuple(created_files)


def _write_seed_file(path: Path, body: str, overwrite: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"

    try:
        with path.open(mode, encoding="utf-8") as project_file:
            project_file.write(body)
            if body and not body.endswith("\n"):
                project_file.write("\n")
    except FileExistsError:
        return False

    return True


def _ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve(strict=False)
    child_resolved = child.resolve(strict=False)

    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Project file path escapes parent directory: {child}") from exc
