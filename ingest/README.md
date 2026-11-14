# Meeting ingest

Audio file -> stored audio -> transcript -> summary -> extracted action items -> Postgres (Supabase),
with a repository layer and a CLI. Lives in `ingest/`, separate from the FastAPI `backend/`
(see `docs/ASSUMPTIONS.md` for why). Read `docs/SCHEMA_NOTES.md` first: the meaning of
`owner_code` was **inferred, not verified**.

```
app/  config  db  models  deadlines  storage  transcription  llm  summarize  extract
      repository  pipeline  cli
tests/  scripts/  docs/        (migrations live in ../supabase/migrations/20261115*.sql)
```

## Setup

```bash
cd ingest
uv venv --python 3.12 .venv            # 3.11+ works for the app; 3.12 is needed for the embedded test DB
uv pip install --python .venv/Scripts/python.exe -e . pytest ruff mypy pgserver   # Windows path; use .venv/bin/python elsewhere
uv pip install --python .venv/Scripts/python.exe -e '.[whisper]'                   # real transcription (faster-whisper)
cp .env.example .env                    # then fill it in; .env is gitignored
```

### Environment variables (`.env.example`)

| var | needed for |
|---|---|
| `SUPABASE_DB_URL` | everything (all table access, psycopg). Missing -> the CLI exits with an error naming it |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | real audio upload (Supabase Storage only) |
| `ANTHROPIC_API_KEY`, `SUMMARY_MODEL`, `EXTRACTION_MODEL` | real summary/extraction (model IDs are never hard-coded) |
| `WHISPER_MODEL` | faster-whisper size/name, default `small` |
| `AUDIO_BUCKET` | default `meeting-audio` |
| `OWNER_CODE_KIND` | `seat` (default) / `person` / `mixed`: what `tasks.owner_code` refers to |

## Apply the migrations to your database (you do this, once)

Nothing in this project has touched your Supabase database. Migrations are additive: they never
alter `tasks` or `tasks_placeholder`.

```bash
export SUPABASE_DB_URL='postgresql://...'      # or set it in .env
./scripts/apply_migrations.sh                  # shows the masked target, asks you to type 'yes'
```

Requires `psql`. Per-file transactions, tracked in `public.ingest_migrations`, safe to re-run.
Optionally run `python scripts/discover.py` first: it is strictly read-only
(`default_transaction_read_only=on`, SELECTs only) and prints what the real `tasks` data looks like,
so you can confirm or correct the codes assumption. Do not commit its output.

## Run the tests

```bash
.venv/Scripts/python.exe -m pytest            # everything except the live test
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
```

The DB-level tests need a real PostgreSQL. They use `pgserver` (an embedded PostgreSQL 16 started
from pip, no Docker or admin rights), because the Docker daemon was not running when this was
built. If you have Docker, any Postgres works too: the fixtures only need a server URL
(adapt `pg_admin_url` in `tests/conftest.py`). Each test gets its own database cloned from a
template that has `tests/fixtures/existing_schema.sql` plus the migrations applied.

### Live smoke test (after applying migrations)

```bash
SUPABASE_DB_URL='postgresql://...' .venv/Scripts/python.exe -m pytest -m live tests/test_live.py
```

Creates a test member, meeting and two tasks, updates one, then deletes exactly the ids it created.
`tasks.source` only allows `manual/meeting/sheet/doc/discord`, so rows are tagged with
`tags=['test-live']` / `source_reference='test-live:<token>'` instead of `source='test-live'`.

## CLI

```bash
export SUPABASE_DB_URL=...
python -m app.cli members add --code TREAS --name Treasurer --kind seat --alias treasurer
python -m app.cli members add --code BOBN --name "Bob Newman" --seat Secretary
python -m app.cli members list

# end to end with fake transcriber / LLM / storage (the database IS still written)
python -m app.cli ingest sample.wav --title "Board meeting" --held-at 2026-11-13T18:00 --dry-run-fakes
# real providers (needs the Setup extras and env vars above)
python -m app.cli ingest sample.wav --title "Board meeting" --held-at 2026-11-13T18:00 --attendee Bob

python -m app.cli meetings list
python -m app.cli meetings show 1
python -m app.cli tasks list --source meeting --status todo
python -m app.cli tasks add --title "Book room" --month 2026-11 --owner SEC
python -m app.cli tasks update WIN-202611-3 --status done
python -m app.cli search "pizza"
```

All output is JSON. `--held-at` is ISO 8601 (naive = America/New_York). Re-running `ingest` on the
same audio file returns the existing meeting; if it had failed, it resumes from the last good step.
