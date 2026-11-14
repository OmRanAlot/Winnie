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
.env.example                       Backend settings (the backend reads the repo-root .env)

backend/                           Python API. Start by reading backend/app/__init__.py
  app/main.py                        Entry point: creates the app, registers routers
  app/settings.py                    Environment configuration
  app/models.py                      Domain dataclasses: Member, Role, Task, Meeting, Notification, ...
  app/schemas.py                     API request/response shapes (currently: Recording)
  app/routes/                        HTTP endpoints, one file per feature (health, recordings built)
  app/services/                      Business logic (recordings built)
  app/integrations/                  Clients for Google, Discord, email, messaging (none built)
  tests/                             test_<feature>.py, one per feature

frontend/                          PLACEHOLDER dashboard; the UX team's design will replace it
  src/App.tsx                        The conversation recorder UI
  src/lib/api.ts                     Calls to the backend
  src/lib/speech.ts                  Browser speech-to-text wrapper
  tests/speech.test.mjs              Tests for speech.ts

messaging/                         Node sidecar relaying iMessage DMs (Photon) to the backend
  src/index.ts                       The whole service (plan only; nothing built yet)
```

Where to put new code: an endpoint goes in `backend/app/routes/<feature>.py`, the rules behind it
in `backend/app/services/<feature>.py`, a call to an outside system in
`backend/app/integrations/`, and its test in `backend/tests/test_<feature>.py`.

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.13 for you) and Node.js 22.12+ with npm. Commands below use PowerShell, starting in the repository root.

Backend, terminal 1:

```powershell
Copy-Item .env.example .env
Set-Location backend
uv sync
uv run fastapi dev app/main.py
```

Frontend, terminal 2:

```powershell
Copy-Item frontend/.env.example frontend/.env
Set-Location frontend
npm install
npm run dev
```

Open [the dashboard](http://localhost:5173) and [the API docs](http://localhost:8000/docs). The dashboard checks `/api/health` through Vite's local proxy.

On macOS/Linux, use `cp` instead of `Copy-Item` and `cd` instead of `Set-Location`.

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
npm --prefix frontend run build
```

## What exists today

The backend includes browser recordings, health checks, task persistence/imports,
member messaging support and read-only event planning drafts. Proposal persistence,
approval/activation and scheduled reminders remain planned. No credentials are
needed for the starter health check. See the feature guides for integration setup.

Never commit `.env` files, actual member phone numbers, inbox contents, recordings, or private transcripts. Only `VITE_` values are exposed to browser code; put provider credentials in the backend environment.
