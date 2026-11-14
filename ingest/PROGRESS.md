# Progress log
- 04:27 Started. Project lives in ingest/ (separate from backend/ to avoid clobbering backend/app). Embedded Postgres via pgserver on Python 3.12 (docker daemon not running).
- Discovery: SUPABASE_DB_URL unset -> no live discovery. Conventions read from supabase/migrations/20261114080000_create_tasks.sql (task_code trigger WIN-YYYYMM-n, month_code YYYY-MM, status default 'todo', source check). Codes inferred as seats (docs/SCHEMA_NOTES.md).
- Migrations 20261115000001..3 + tests/fixtures/existing_schema.sql written. Migration tests: existing tables snapshot (columns, constraints, indexes, triggers, RLS, row hash) identical before/after applying twice; CHECK/FK/cascade/unique/self-dependency verified. 77 passed.
- Repository, pipeline, CLI, live smoke test written. First full run: 1 failure, real bug: save_transcript on an unknown meeting raised a raw FK error instead of LookupError. Fixed in app/repository.py (update meeting row first, inside the transaction).
- Second failure was a WRONG TEST, not code: test_list_tasks_filters forgot the synthetic fixture row also owned by TREAS. Corrected the expectation (added SEC assertion); nothing weakened.
- ruff: E501 only. Tests ignore E501; line length 120. mypy strict: only no-any-return from psycopg dict rows in app.repository -> warn_return_any off for that module.
- scripts/apply_migrations.sh tested against the throwaway Postgres: found a REAL BUG (this psql build ignores options placed after the connection string, so the script reported success while applying nothing). Fixed via psql -d, added a final recorded-count check and tests/test_apply_script.py as a regression test.
- Full suite: see final entry.
