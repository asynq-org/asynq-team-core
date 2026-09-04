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
- linked follow-up tasks for scoped future improvements;
- authorized task creation that enforces agent `task.create` capability;
- task status updates;
- authorized task comments and mentions;
- agent run records and artifact directories;
- task run start workflow that prepares work context in one call;
- run work packets that collect task, agent, and rule context;
- run result submission for supervisor review;
- supervisor review artifacts and approve/return run decisions;
- local doctor diagnostics for workspace setup and database migrations;
- local SQLite database backups;
- capability policy loading and agent capability evaluation;
- capability authorization that creates approval requests for gated actions;
- task-scoped audit event queries;
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

Create a linked follow-up task:

```python
from asynq_team_core.task_service import create_follow_up_task

follow_up = create_follow_up_task(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    parent_task_id=created.task.id,
    title="Document review checklist",
    brief_md="Capture the checklist as a future scoped improvement.",
    actor_type="agent",
    actor_id="george",
)

print(follow_up.task.id)
print(follow_up.task.parent_task_id)
```

Update task status:

```python
from asynq_team_core.database import connect_database
from asynq_team_core.tasks import TaskStatus, update_task_status

with connect_database(initialization.layout.database_path) as connection:
    update_task_status(
        connection,
        created.task.id,
        TaskStatus.IN_PROGRESS,
        actor_type="agent",
        actor_id="george",
    )
```

Start a task run and prepare its work packet:

```python
from asynq_team_core.run_task import start_task_run

started = start_task_run(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    task_id=created.task.id,
    agent_id="george",
    actor_type="agent",
    actor_id="george",
)

run = started.work_packet.run
print(run.id)
print(started.work_packet.artifact.relative_path)
```

Or prepare a run work packet for an existing run:

```python
from asynq_team_core.run_service import create_run_with_artifact_dir
from asynq_team_core.run_work import prepare_run_work_packet

run = create_run_with_artifact_dir(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    task_id=created.task.id,
    agent_id="george",
    actor_type="human",
    actor_id="founder",
).run

packet = prepare_run_work_packet(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    run_id=run.id,
    actor_type="agent",
    actor_id="george",
)

print(packet.artifact.relative_path)
```

Submit a run for review:

```python
from asynq_team_core.run_submission import submit_run_for_review

submission = submit_run_for_review(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    run_id=run.id,
    summary_md="Implemented the first pass.",
    checks_md="- poetry run pytest",
    reviewer_id="supervisor",
    actor_type="agent",
    actor_id="george",
)

print(submission.artifact.relative_path)
print(submission.run.status.value)
```

Review a submitted run:

```python
from asynq_team_core.run_review import RunReviewDecision, review_run

review = review_run(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    run_id=run.id,
    decision=RunReviewDecision.APPROVE,
    body_md="Looks ready.",
    actor_type="agent",
    actor_id="supervisor",
)

print(review.artifact.relative_path)
print(review.run.status.value)
```

Run workspace diagnostics:

```python
from asynq_team_core.doctor import run_doctor

report = run_doctor(initialization.layout)
for check in report.checks:
    print(check.status.value, check.name, check.message)
```

Create and list local database backups:

```python
from asynq_team_core.backups import create_database_backup, list_database_backups

backup = create_database_backup(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    actor_type="human",
    actor_id="founder",
)

print(backup.relative_path)
print([item.relative_path for item in list_database_backups(initialization.layout)])
```

Show task-scoped audit events:

```python
from asynq_team_core.audit import list_task_audit_events

for event in list_task_audit_events(initialization.layout.database_path, created.task.id):
    print(event.created_at, event.event_type, event.actor_id)
```

Evaluate an agent capability:

```python
from asynq_team_core.policy import CapabilityDecision, evaluate_agent_capability

evaluation = evaluate_agent_capability(
    initialization.layout,
    agent_id="george",
    capability="main.merge",
)

if evaluation.decision is CapabilityDecision.REQUIRE_APPROVAL:
    print("Ask for approval before continuing.")
```

Authorize a capability and create an approval when required:

```python
from asynq_team_core.policy import authorize_agent_capability

authorization = authorize_agent_capability(
    database_path=initialization.layout.database_path,
    layout=initialization.layout,
    agent_id="george",
    capability="main.merge",
    reason="Merge reviewed changes.",
    subject_type="run",
    subject_id=run.id,
)

if authorization.approval_request:
    print(authorization.approval_request.approval.id)
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
