# Asynq Team Core

Core package for Asynq Team.

This package will own:

- domain models;
- persistence interfaces;
- config loading;
- agent manifests;
- task and run state;
- events and audit records;
- comments, mentions, inboxes, and approvals;
- policy and capability checks;
- artifact paths and writers;
- runner adapter interfaces.

Interfaces such as CLI, MCP, dashboards, desktop apps, mobile apps, and hosted services should call this package rather than reimplementing domain behavior.

