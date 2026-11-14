# Winnie

An iMessage-first AI coordinator for the NJIT Women in Computing Society (WiCS) e-board, built for HackPrinceton.

Winnie turns meeting context into proposed event plans, asks the President to approve them, and helps members update their tasks with a text.

Start with [CONTEXT.md](CONTEXT.md) for product and implementation decisions, [docs/GAMEPLAN.md](docs/GAMEPLAN.md) for the build sequence and demo checklist, and [docs/architecture.md](docs/architecture.md) for open architecture decisions. `CLAUDE.md` holds the product spec.

## Repository

| Service | Path | Stack |
|---|---|---|
| API + agent logic | `backend/` | Python 3.13, uv, FastAPI |
| DM interface | `messaging/` | Node, TypeScript, Photon (`@photon-ai/advanced-imessage`) |
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

## Checks

```powershell
Set-Location backend; uv run pytest; uv run ruff check .
npm --prefix frontend run build
```

## What exists today

This is a development scaffold: a browser conversation recorder (audio + transcript saved as JSON), the API health and recordings endpoints, configuration loading, and tests for both. Agent planning, member/task persistence, approval enforcement, messaging, and reminders are planned in the linked documents; they are not implemented yet. No credentials are needed for the starter health check. Settings marked as future in `.env.example` are reserved for later phases.

Never commit `.env` files, actual member phone numbers, inbox contents, recordings, or private transcripts. Only `VITE_` values are exposed to browser code; put provider credentials in the backend environment.
