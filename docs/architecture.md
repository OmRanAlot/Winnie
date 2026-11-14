# Architecture

```
            Google Sheets / Docs     Discord     Shared inbox     Meeting audio
                      \                |              |               /
                       +---------- backend/integrations -------------+
                                           |
   frontend/ (React) <---- REST ---->  backend/ (FastAPI)  <---- webhooks / POST /send ----> messaging/ (Node) <-> Photon <-> iMessage
                                           |
                                        database
```

## Responsibilities
- **backend/** owns all data and decisions: tasks, dependencies, routing, reassignment, notifications, schedules.
- **messaging/** only moves messages between Photon and the backend. It exists because Photon has no Python SDK.
- **frontend/** is a placeholder. The UX team's design will replace it, built against the backend schemas.

## Open decisions
- Database (SQLite for dev; Postgres for prod?)
- Auth for the web UI
- Shared-inbox provider (Gmail API vs IMAP)
- Transcription provider
- Hosting for each service
