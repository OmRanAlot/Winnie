# Ingestion verification — 2026-11-14

Ingestion is in the existing backend. The separate `ingest/` directory is absent.
The entry point is `POST /api/meetings/ingest`, registered in `backend/app/main.py`.
Its implementation is `backend/app/routes/meetings.py` and
`backend/app/services/meeting_ingest.py`, reusing the existing extraction and repository code.

## Verified

- The initial full backend run passed: **248 tests** (`cd backend; uv run pytest -q`).
- The ingestion test module passed: **6 tests**, covering successful persistence with fakes,
  duplicate uploads, unsupported MIME types, empty/oversized files, a missing Gemini key,
  and a Gemini failure.
- A real Gemini request accepted a synthetic WAV file.
- A second real-provider check sent synthesized speech through the HTTP upload endpoint.
  Gemini correctly transcribed two actions, generated a summary, and assigned both tasks.
  The response was HTTP 200; one meeting, its summary, two tasks, and the audio file were
  saved using an isolated fake database and a temporary recordings directory.
  This used the real two Gemini calls, but **did not test live database persistence**.
- The summary migration applied twice successfully to the legacy schema in a fresh,
  temporary PGlite PostgreSQL database.
- Ruff passes for the ingestion route, service, and tests. Mypy passes for the ingestion
  route and service with `--follow-imports=silent`. A missing-key guard was added to the
  service to resolve the optional-key type error.

## Blocking real database verification

- Backend settings contain a Supabase URL but no `SUPABASE_SERVICE_ROLE_KEY`.
  No live database writes or migrations were run.
- The ingestion repository expects the legacy `tasks` schema: bigint IDs, `seat_id`,
  `assignee_id`, `source_meeting_id`, and `deadline_at`.
  The existing UUID/code-based task schema uses different columns and statuses.
- `0001_init.sql` and `20261114080000_create_tasks.sql` both create `public.tasks` with
  those incompatible definitions. Running them in order in local PostgreSQL reproduced
  SQLSTATE **42P07**, `relation "tasks" already exists`.
  Adding the summary column alone does not reconcile these schemas.
- Audio is saved on the backend's local disk, not in Supabase Storage.

## Broader repository checks

A subsequent full-suite run encountered collection errors in `test_agents_runner.py`
and `test_agents_stages.py`: their imports of `describe_model` and `StageRunner` were
unavailable. These files changed during verification and are outside ingestion.
Full-repository Ruff also reported nine issues in planning/agent test files.
The initial 248-test result is not a claim that the subsequently changed whole repository
is green.

Before deployment, adapt ingestion persistence to the UUID/code-based task schema, reconcile
the conflicting migration files without changing existing live task data, and configure the
service-role key. Real database persistence remains unverified until that work is complete.

## Follow-up: secret-key configuration

The backend now accepts `SUPABASE_SECRET_KEY` (and `WINNIE_SUPABASE_SECRET_KEY`),
while retaining the legacy service-role aliases. The configured local secret and URL were
successfully used for read-only, zero-row schema probes. No row contents were retrieved:

- UUID/code-based task columns are available.
- Legacy task columns are absent (`42703`, `tasks.seat_id` does not exist).
- `public.meetings` is absent from the PostgREST schema cache (`PGRST205`).

This resolves the earlier missing-credential observation. It confirms that the current live
API schema cannot support the existing ingestion repository. No live writes or DDL were run.
The targeted task API and ingestion suite passes **24 tests** after adding alias coverage.
