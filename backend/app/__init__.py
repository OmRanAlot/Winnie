"""Winnie backend (FastAPI). Start here to find your way around.

WHAT IS WHERE (every folder has its own __init__.py docstring with the file-by-file detail)
    main.py        The only file at this level. Creates the FastAPI app and registers every
                   router. Run this file.
    core/          App-wide plumbing: settings.py (env config, prefix WINNIE_, repo-root .env),
                   logging_config.py, deadlines.py (spoken deadline -> America/New_York datetime).
    domain/        models.py: Member, Role, Meeting, Notification, ... (dataclasses) and
                   ExtractedTask / Task / TaskDependency (Pydantic, mirror the Supabase tables).
    schemas/       Pydantic shapes that cross a boundary: api.py (Recording, TaskView, the
                   response envelope), tasks.py, planning.py, pipeline.py.
    db/            repository.py: Supabase reads/writes for seats, people, meetings, tasks, deps.
    routes/        HTTP endpoints. One file per feature. Thin: validate, call a service.
    services/      Business logic. No HTTP objects in here.
    agents/        All LangChain / Deep Agents code (planning drafts). Propose-only, no tools.
    integrations/  Clients for outside systems (Google, Discord, email, messaging).
    cli/           `python -m app.cli.<name>` tools: imports, previews, demo user.
    ../tests/      pytest. One test file per feature, named test_<feature>.py.

HOW A REQUEST FLOWS
    routes/  ->  services/  ->  integrations/ (when an outside system is involved)
    Routes never call integrations directly. Services never import FastAPI.

BUILT TODAY
    GET  /api/health         routes/health.py
    POST /api/recordings     routes/recordings.py -> services/recordings.py -> schemas/api.py Recording
    POST /api/recordings/{id}/assignments  -> services/meeting_tasks.py (Gemini, then Supabase)
    GET  /api/tasks, PATCH /api/tasks/{id}/status  routes/tasks.py -> services/tasks.py
                             -> db/repository.py -> integrations/supabase_client.py
    POST /api/planning/drafts routes/planning.py -> services/planning.py -> agents/planner.py
                             Read-only historical checklist or Deep Agents draft; no activation.
    POST /api/planning/pipeline-drafts  routes/planning.py -> services/planning_pipeline.py
                             -> agents/stages.py (one Deep Agents call per stage).
    All LangChain / Deep Agents code lives in agents/ (map and call flow in agents/__init__.py).
    Nothing outside agents/ imports langchain or deepagents.
    Everything listed as "Planned" in routes/, services/ and integrations/ is not built yet.

PLANNED, NOT BUILT (no files exist for these on purpose; create them when the feature lands)
    database      DONE differently: Supabase (Postgres) via supabase-py, see db/repository.py and
                  supabase/migrations/. Members, notifications etc. still live only in
                  domain/models.py.
    jobs.py       Scheduled sweeps, run by a SEPARATE worker process (APScheduler):
                    - deadline sweep (hourly): see services/deadlines.py
                    - email reminder sweep
                    - Google Sheets / Docs sync
                  Never start the scheduler at FastAPI import time: dev reload or multiple API
                  workers would duplicate every send. One worker, with durable notification dedupe.
    agents/       Planners exist (see BUILT TODAY); proposal persistence, revision editing,
                  approval and activation still need implementation. Keep model-provider imports
                  inside agents/, out of routes and services, and never give an agent
                  unrestricted write/send tools (agents/runner.py builds them tool-free).
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
