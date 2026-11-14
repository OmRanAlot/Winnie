"""Winnie backend (FastAPI). Start here to find your way around.

WHAT IS WHERE
    main.py        Creates the FastAPI app and registers every router. Run this file.
    settings.py    Environment configuration (reads the repo-root .env, prefix WINNIE_).
    models.py      Domain objects: Member, Role, Task, Meeting, Notification, ...
                   Plain dataclasses with validation. Not database tables.
    schemas.py     API request/response shapes (what crosses HTTP). Currently: Recording.
    routes/        HTTP endpoints. One file per feature. Thin: validate, call a service.
    services/      Business logic. No HTTP objects in here.
    integrations/  Clients for outside systems (Google, Discord, email, messaging).
    ../tests/      pytest. One test file per feature, named test_<feature>.py.

HOW A REQUEST FLOWS
    routes/  ->  services/  ->  integrations/ (when an outside system is involved)
    Routes never call integrations directly. Services never import FastAPI.

BUILT TODAY
    GET  /api/health         routes/health.py
    POST /api/recordings     routes/recordings.py -> services/recordings.py -> schemas.Recording
    POST /api/planning/drafts routes/planning.py -> services/planning.py -> agents/planner.py
                             Read-only historical checklist or Deep Agents draft; no activation.
    Everything listed as "Planned" in routes/, services/ and integrations/ is not built yet.

PLANNED, NOT BUILT (no files exist for these on purpose; create them when the feature lands)
    database.py   SQLAlchemy 2.x engine + session factory + a `get_session` FastAPI dependency.
                  Database not chosen: SQLite for local dev, likely Postgres in prod
                  (docs/architecture.md). Add Alembic migrations (`uv run alembic init migrations`)
                  once tables exist. Repositories (find/create/update per table) are deliberately
                  skipped until there is real persistence; call the session from services at first.
    jobs.py       Scheduled sweeps, run by a SEPARATE worker process (APScheduler):
                    - deadline sweep (hourly): see services/deadlines.py
                    - email reminder sweep
                    - Google Sheets / Docs sync
                  Never start the scheduler at FastAPI import time: dev reload or multiple API
                  workers would duplicate every send. One worker, with durable notification dedupe.
    agents/       Draft planner exists; proposal persistence, revision editing, approval and
                  activation still need implementation. Keep model-provider imports out of routes,
                  and never give an agent unrestricted write/send tools.
    schemas.py    Add the {success, data, error, meta} response envelope and Pagination
                  {total, page, limit}. Add per-feature request/response shapes next to Recording.
    main.py       Lifespan hook (open DB engine, shut down cleanly); global error handler that
                  returns the envelope; webhook-signature and "current member" dependencies
                  (auth approach still to be decided).
    settings.py   Fields for the integrations below, failing fast at startup when a required
                  secret is missing: DATABASE_URL, GOOGLE_SERVICE_ACCOUNT_FILE, TASK_TRACKER_SHEET_ID,
                  MEETING_NOTES_FOLDER_ID, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, SHARED_INBOX_ADDRESS,
                  MESSAGING_SIDECAR_URL, MESSAGING_WEBHOOK_SECRET, EMAIL_REMINDER_AFTER_HOURS,
                  DEADLINE_WARNING_DAYS. (Browser recordings need no transcription key.)
    tests/        conftest.py fixtures: API test client, fake integrations, a seeded 12-member
                  e-board including the two-seat roles.
"""
