# Asynq Team Core

`asynq-team-core` is the Python runtime library for local-first Asynq Team workspaces.

Asynq Team is a local-first operating layer for working with AI agents as a small software team. Instead of treating agent work as disposable chat history, it keeps tasks, plans, approvals, audit events, and human decisions in a project-local workspace that can be inspected, tested, and versioned.

The goal is to make agent-assisted development more reliable:

- agents work from explicit tasks instead of ad hoc prompts;
- human approvals gate sensitive actions;
- audit records explain what happened and who requested it;
- Markdown artifacts stay easy to review in git;
- SQLite keeps runtime state queryable without requiring hosted infrastructure;
- the same core runtime can support a CLI now and richer interfaces later.

It provides the domain and persistence building blocks used by the CLI and future interfaces:

- project initialization for `.team/` workspaces;
- local SQLite database setup and migrations;
- task records and Markdown task briefs;
- task comments and mentions;
- append-only audit events;
- default agent, rule, and policy file seeding;
- approval requests and inbox items for human attention.

The package is early and pre-1.0. APIs may change while the MVP is still taking shape.

## Install From Source

```bash
git clone git@github.com:asynq-org/asynq-team-core.git
cd asynq-team-core
poetry install
```

## Basic Usage

Initialize a local workspace:

```python
from pathlib import Path

from asynq_team_core.database import initialize_database
from asynq_team_core.project import initialize_project

workspace = Path.cwd()
initialization = initialize_project(workspace, project_name="Example Team")
initialize_database(initialization.layout.database_path)
```

Create a task with a Markdown brief:

```python
from asynq_team_core.task_service import create_task_with_brief

created = create_task_with_brief(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    title="Review the onboarding flow",
    brief_md="Check the first-run setup and list blockers.",
    actor_type="human",
    actor_id="founder",
)

print(created.task.id)
print(created.brief.relative_path)
```

Request and decide an approval:

```python
from asynq_team_core.approvals import grant_approval, request_approval
from asynq_team_core.database import connect_database

with connect_database(initialization.layout.database_path) as connection:
    requested = request_approval(
        connection,
        action="main.merge",
        reason="Merge reviewed changes.",
        requester_type="agent",
        requester_id="george",
        approver_id="founder",
    )
    grant_approval(
        connection,
        requested.approval.id,
        actor_type="human",
        actor_id="founder",
        reason="Reviewed locally.",
    )
```

## Development

Use Poetry for local development:

```bash
poetry install
poetry run python scripts/check_release_metadata.py
poetry run ruff check .
poetry run pytest
poetry run pip-audit
```

Before committing package-relevant changes, update `project.version` and add a release-note fragment under `.release-notes/`.
