# Assumptions

1. **Live discovery did not run.** `SUPABASE_DB_URL` was unset. Nothing was verified against real
   data; conventions come from `supabase/migrations/20261114080000_create_tasks.sql`. See SCHEMA_NOTES.md.
2. **DB_TARGET unknown -> treated as live production.** No connection to any Supabase database was
   opened. All testing used a local throwaway Postgres. Migrations are files for you to apply with
   `scripts/apply_migrations.sh`.
3. **CODES_MEANING unknown -> inferred "seats"**, switchable with `OWNER_CODE_KIND` (SCHEMA_NOTES.md).
4. **Location.** The repo already has `backend/app/` (FastAPI) with its own `deadlines.py` and
   `repository.py`. To avoid overwriting it, this lives in a separate package at `ingest/` with its own
   `app/` (so `python -m app.cli` works from `ingest/`). `app/deadlines.py` is a copy of the backend one.
5. **Migration names** are `20261115000001..3_*.sql` (timestamp style, sorting after the existing
   `20261114080000`), not `0001..`, because `0001_init.sql` already exists. The apply script runs only
   these three; it deliberately ignores `0001_init.sql` (stale, conflicts, see SCHEMA_NOTES.md).
6. **Test Postgres.** The Docker daemon was not running, so tests use `pgserver` (embedded
   PostgreSQL 16, pip-installable). It needs Python <= 3.12 wheels, so the dev venv is 3.12; the code
   targets 3.11+.
7. **The fixture's `tasks` trigger is copied from the repo migration** (not read from the live DB).
8. **`tasks.source` cannot be `test-live`** (CHECK constraint). The live smoke test tags rows with
   `tags=['test-live']`, `source_reference='test-live:<token>'` and deletes exactly the ids it created.
9. **Task owner/deadline are never guessed.** Unresolved or ambiguous seats/assignees and unparseable
   deadlines leave `owner_code` / `due_date` NULL and set `task_meeting_links.needs_review`.
10. **Members are never auto-created** by the pipeline (an LLM could invent names). Unknown attendees
    are reported in the ingest output. `get_or_create_member(..., create_missing=True)` exists for
    explicit use.
11. **Whole transcript goes to the LLM in one call** (no chunking); audio is read fully into memory for
    upload. Fine for board meetings, revisit for multi-hour audio. Whisper does no diarization, so
    `speaker_label`/`member_id` on segments stay NULL.
12. **Real providers were not exercised** (no keys, no audio model downloaded): Anthropic, Supabase
    Storage, faster-whisper. They sit behind Protocols and are covered only by fakes. `faster-whisper`
    is an optional extra (`pip install -e '.[whisper]'`).
13. **Idempotency key** is the SHA-256 of the audio bytes. Re-ingesting a failed meeting resumes; a
    `done` meeting is returned unchanged (title/held_at args are ignored on re-ingest).
14. **Resume** derives the next step from saved data (no transcript -> transcribe; no summary ->
    summarize; else extract), and `insert_extracted_tasks` is a no-op if the meeting already has links.
15. **Tooling choices:** ruff line length 120; mypy `warn_return_any` off for `app.repository` only
    (psycopg rows are `dict[str, Any]`).
