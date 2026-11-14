# Winnie backend

FastAPI service managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # create .venv and install deps
cp .env.example .env             # fill in secrets
uv run fastapi dev app/main.py   # dev server
uv run pytest                    # all tests
uv run pytest tests/test_x.py::test_name   # single test
uv run ruff check .              # lint
```

`app/__init__.py` is the map of this package: what each file is, how a request flows, what is built, and what is planned.

## Semester task trackers

Task CRUD uses Supabase. The backend loads `WINNIE_SUPABASE_URL` and
`WINNIE_SUPABASE_SECRET_KEY` from the repository-root `.env`, not `messaging/.env`.
Apply both SQL migrations in order before using the expanded task fields.
See [tracker import setup](../docs/TRACKER_IMPORT.md) for migration steps, monthly
snapshot rules, permanent task IDs, the offline CSV/TSV preview, and the reviewed
Supabase import command (`python -m app.import_tracker`). Imports default to a
database preview; actual writes require `--apply --expect-plan <plan_id>`.
Live Google Sheets synchronization is not implemented yet.

### Google Sheets source selection and semester rollover

A **spreadsheet** is the whole Google Sheets workbook; a **tab** is a sheet inside it.
The spreadsheet ID is the part of its URL between `/d/` and `/edit`:

```text
https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=TAB_ID
```

Use the ID of the workbook the CSV came from. For example, an April 2026 export
from Spring 2026 must use the Spring workbook's ID, even when Fall is the current
semester. The spreadsheet ID identifies the source; it does not authorize Google access.

| When | What to change |
|---|---|
| Update the same active tab | Export it again; keep the spreadsheet ID, semester, and task IDs |
| Duplicate the tracker for a new month | Keep the spreadsheet ID and semester; change `--tab` and optional `--tab-id`; preserve existing task IDs |
| Start a new semester with a new workbook | Use its new `--spreadsheet-id` and `--semester`, and select its active tab |
| Import a separate GirlHacks workbook | Use that workbook's ID and `--project "GirlHacks 2026"`; if GirlHacks is a tab in the semester workbook, keep the semester workbook ID |

Each import command names its source explicitly. Changing the next command's source
does not relabel or delete earlier tasks in Supabase. Existing tasks in the same
workbook must keep their `Winnie Task ID` across copied tabs; new tasks get new IDs.
Task IDs must be unique across current task lists within a workbook, including
GirlHacks if it is in that same workbook. Archived OLD tabs are excluded from writes.

Do not switch a previously imported CSV from a demo source ID to a real source ID:
Supabase would treat it as a different source. Use the real ID from the first save.
Keep old semester records and link carried-over work explicitly rather than assuming
matching titles in different workbooks are the same task.

Currently the importer reads an exported CSV/TSV and uses this ID for task identity.
A live private-sheet connection will additionally need authorized Google read access
and a configured active tab per tracker. There are no working automatic Google sync
or Google source-selection environment settings yet. Follow the
[import guide](../docs/TRACKER_IMPORT.md#preview-against-supabase-then-save) for the
implemented preview/apply commands.

## Login profiles

Supabase Auth owns login credentials. The `public.profiles` migration adds name,
email, phone number, board role, admin status, and skills, with owner-only browser
access and protected role/admin fields. See [auth setup](../docs/AUTH_SETUP.md) for
applying the migration, creating a demo login, and reading/editing profiles.

## Personal messaging setup

See [personal iMessage tasks](../docs/MESSAGING_MEMBERS.md) to apply the member
migration, configure the shared bridge secret, register sender identities, and map
tracker names/emails to members. `tasks` now returns only verified assignments for
the sender in `WINNIE_ACTIVE_SEMESTER`, ordered by deadline. Unknown members receive
no task list. This mapping is separate from website login.

## Event planning drafts

`POST /api/planning/drafts` returns a historical checklist in mock mode or an
idea-specific draft through the optional Deep Agents adapter. See the
[planning guide](../docs/EVENT_PLANNING.md) for private context preparation,
model setup and limitations. Drafts do not create tasks or send messages.

## Browser recordings

The frontend performs recording and transcription with browser APIs. No transcription provider or API key is used by the backend.

`POST /api/recordings` accepts the self-contained JSON documented in `frontend/README.md`, validates base64 audio and metadata, and saves a uniquely named file under `backend/data/recordings/`. The success envelope returns `data.filename`. Audio is limited to 10 MB and JSON requests to 15 MB. Saved files are gitignored. This is local development storage; the endpoint has no authentication and should not be exposed publicly without access controls.
