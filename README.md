# Winnie

An iMessage-first AI coordinator for the NJIT Women in Computing Society (WiCS) e-board, built for HackPrinceton.

Winnie turns meeting context into proposed event plans, asks the President to approve them, and helps members update their tasks with a text.

Start with [CONTEXT.md](CONTEXT.md) for product and implementation decisions, [docs/GAMEPLAN.md](docs/GAMEPLAN.md) for the build sequence and demo checklist, and [docs/architecture.md](docs/architecture.md) for open architecture decisions. `CLAUDE.md` holds the product spec.

## Repository

| Service | Path | Stack |
|---|---|---|
| API + agent logic | `backend/` | Python 3.13, uv, FastAPI |
| DM interface | `messaging/` | Node, TypeScript, Photon Spectrum (`spectrum-ts`) |
| Web dashboard (placeholder) | `frontend/` | Vite, React, TypeScript |

### Repository map

Every real source file starts with a comment saying what it is and who calls it. Folders that
hold planned-but-unbuilt work describe it in their `__init__.py` docstring (backend) or the top
comment of `index.ts` (messaging), instead of empty placeholder files.

```text
README.md, CLAUDE.md, CONTEXT.md   Overview, agent instructions + product spec, implementation contract
docs/                              GAMEPLAN.md (build order), API.md (proposed endpoints), architecture.md
supabase/migrations/0001_init.sql  Postgres schema for the task store (seats, people, meetings, tasks, deps)
.env.example                       Backend settings (the backend reads the repo-root .env)

backend/                           Python API. Start by reading backend/app/__init__.py
  app/main.py                        Entry point: creates the app, registers routers
  app/settings.py                    Environment configuration
  app/models.py                      Domain objects; ExtractedTask / Task / TaskDependency mirror the DB
  app/schemas.py                     API request/response shapes (Recording, TaskView)
  app/deadlines.py                   "by Monday noon" -> datetime (America/New_York), None if unsure
  app/repository.py                  Supabase reads/writes: seats, people (alias matching), tasks, deps
  app/routes/                        HTTP endpoints, one file per feature (health, recordings, tasks)
  app/services/                      Business logic (recordings, task assignment, task store)
  app/integrations/                  Clients for outside systems (supabase_client.py built)
  scripts/seed_example.py            Inserts a sample meeting + 3 tasks, prints list_tasks()
  tests/                             test_<feature>.py, one per feature; fake_supabase.py fakes the DB

frontend/                          PLACEHOLDER dashboard; the UX team's design will replace it
  src/App.tsx                        The conversation recorder UI, plus <Timeline />
  src/features/timeline/             Gantt of all tasks (self-contained; delete to replace)
  src/lib/api.ts                     Calls to the backend (TaskView is the timeline contract)
  src/lib/speech.ts                  Browser speech-to-text wrapper
  tests/*.test.mjs                   Tests for speech.ts and the timeline layout (npm test)

messaging/                         Node sidecar relaying iMessage DMs (Photon) to the backend
  src/index.ts                       The whole service (plan only; nothing built yet)
```

Where to put new code: an endpoint goes in `backend/app/routes/<feature>.py`, the rules behind it
in `backend/app/services/<feature>.py`, a call to an outside system in
`backend/app/integrations/`, and its test in `backend/tests/test_<feature>.py`.

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.13 for you), Node.js 22.12+ with npm, and [Docker Desktop](https://www.docker.com/products/docker-desktop/) (only for the local database). Commands below use PowerShell, starting in the repository root. On macOS/Linux, use `cp` instead of `Copy-Item` and `cd` instead of `Set-Location`.

### Local mode (recommended)

`WINNIE_MODE` is `local` for any local testing and `prod` for deployments (the default). Local mode reads gitignored `.env.local` files that are never built into the Cloud Run image or the Firebase bundle, and the backend refuses to start if `SUPABASE_URL` points anywhere but your machine, so nothing you do on localhost can touch the deployed database.

1. **Start the local database** (Docker must be running; migrations in `supabase/migrations/` are applied automatically):

   ```powershell
   npm install                  # once, at the repo root: installs the Supabase CLI
   npx supabase start
   npx supabase status -o env   # prints the API URL plus the publishable (anon) and secret (service-role) keys
   ```

2. **Configure the backend.** Copy the template, then paste the secret (service-role) key into `SUPABASE_SECRET_KEY`. `WINNIE_MODE=local` and `SUPABASE_URL=http://127.0.0.1:54321` are already set. Optionally add your own `GEMINI_API_KEY` for task assignment.

   ```powershell
   Copy-Item .env.local.example .env.local
   ```

3. **Configure the frontend.** Copy the template, then paste the publishable (anon) key into `VITE_SUPABASE_PUBLISHABLE_KEY`.

   ```powershell
   Copy-Item frontend/.env.localdev.example frontend/.env.localdev
   ```

4. **Run the backend**, terminal 1:

   ```powershell
   Set-Location backend
   uv sync
   uv run fastapi dev app/main.py
   ```

5. **Run the frontend**, terminal 2:

   ```powershell
   Set-Location frontend
   npm install
   npm run dev:local
   ```

Open [the dashboard](http://localhost:5173) and [the API docs](http://localhost:8000/docs). The dashboard reaches the backend through Vite's `/api` proxy to port 8000. The backend's startup log shows `mode=local`; if it says `mode=prod`, your `.env.local` was not picked up. Stop the database with `npx supabase stop`.

The messaging sidecar (`messaging/`) is optional. To use it locally, set the same `MESSAGING_BRIDGE_SECRET` in `messaging/.env` as `WINNIE_MESSAGING_BRIDGE_SECRET` in `.env.local`, then run `npm install; npm run dev` there.

### Quick start without a database

If you only want the UI and API shell, skip Docker and Supabase. Task endpoints will return 503, but `/api/health` and the docs work:

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env
Set-Location backend; uv sync; uv run fastapi dev app/main.py   # terminal 1
Set-Location frontend; npm install; npm run dev                  # terminal 2
```

Never use `npm run dev:local` or `.env.local` values for a deploy: production config lives only in Cloud Run env vars and Secret Manager (see [docs/CI.md](docs/CI.md)).

## Task tracker setup

See [Google Sheets source selection and semester rollover](backend/README.md#google-sheets-source-selection-and-semester-rollover)
for choosing the spreadsheet ID, selecting the active monthly tab, and switching
to a new semester's workbook. Use the workbook that the data came from: historical
Spring exports keep the Spring workbook ID even when Fall is the current semester.

The current importer reads CSV/TSV exports and saves reviewed changes to Supabase.
Live access to private Google Sheets and automatic recurring sync are not implemented
yet. The [import guide](docs/TRACKER_IMPORT.md) covers database setup, permanent task
IDs, previewing changes, and applying an import.

## Checks

Event planning now has a read-only draft endpoint, historical calendar/tracker
matching, an offline checklist mode and an optional LangChain Deep Agents adapter.
See the [event planning guide](docs/EVENT_PLANNING.md) for setup and sample requests.

```powershell
Set-Location backend; uv run pytest; uv run ruff check .
npm --prefix frontend run build; npm --prefix frontend test
```

## Task store (Supabase)

Every task Gemini extracts from a recording is saved to Supabase (Postgres) and shown on the
dashboard's timeline. Without Supabase settings the recorder still works, but tasks are not saved
(the API logs a warning and `GET /api/tasks` returns 503).

1. **Create a project** at [supabase.com](https://supabase.com/dashboard) (free tier is fine).
   Note the database password you choose.
2. **Apply the migration** `supabase/migrations/0001_init.sql`, either way:
   - SQL editor: Dashboard -> SQL Editor -> New query, paste the file, Run.
   - CLI, from the repository root:
     ```powershell
     npx supabase login
     npx supabase link --project-ref <your-project-ref>   # asks for the database password
     npx supabase db push
     ```
3. **Set the backend environment.** Dashboard -> Project Settings -> API Keys gives the
   `service_role` secret key; the project URL is `https://<your-project-ref>.supabase.co`. Put them
   in `.env` (repo root) or `backend/.env`:
   ```dotenv
   SUPABASE_URL=https://<your-project-ref>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<service_role secret>
   ```
   The service-role key bypasses row-level security, so it stays server-side: never in
   `frontend/.env`, never committed, never logged (the API only logs "set"/"MISSING").
   All tables have RLS enabled with no policies, so the public anon key can read nothing.
4. **Seed and check:**
   ```powershell
   Set-Location backend
   uv run python -m scripts.seed_example        # sample meeting + 3 tasks, then prints list_tasks()
   ```
   Start the API and dashboard (see *Run locally*); the tasks appear on the timeline, ordered by
   deadline and colored by assignee. `GET /api/tasks?status=open&assignee=Bob&seat=Treasurer`
   filters; `PATCH /api/tasks/{id}/status` with `{"status": "done"}` checks a task off.

Deadlines are parsed from what was said ("tonight", "Monday morning", "by Monday noon") against
the meeting time in America/New_York (`backend/app/deadlines.py`). Anything else is stored as said
in `deadline_raw` with no date and listed as *Unscheduled*, never guessed.

**Replacing the frontend:** the timeline only uses `GET /api/tasks` and
`PATCH /api/tasks/{id}/status` (shape: `TaskView` in `backend/app/schemas.py`). Delete
`frontend/src/features/timeline/` and its one line in `App.tsx`, and build the new UI against
those two endpoints. The browser never talks to Supabase directly.

## What exists today

This is a development scaffold: a browser conversation recorder (audio + transcript saved as JSON), Gemini task assignment, a Supabase task store with a Gantt timeline, the API health, recordings and tasks endpoints, configuration loading, and tests. Agent planning, member persistence, approval enforcement, messaging, and reminders are planned in the linked documents; they are not implemented yet. No credentials are needed for the starter health check. Settings marked as future in `.env.example` are reserved for later phases.

The backend also includes task imports, member messaging support and read-only event planning
drafts (`POST /api/planning/drafts`). Proposal persistence, approval/activation and scheduled
reminders remain planned. See the feature guides for integration setup.

Never commit `.env` files, actual member phone numbers, inbox contents, recordings, or private transcripts. Only `VITE_` values are exposed to browser code; put provider credentials in the backend environment.
