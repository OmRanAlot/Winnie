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

```text
docs/                 Execution plan, API contract, architecture
.env.example          Backend settings, including future integration placeholders
frontend/.env.example Public browser settings only
```

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

This is a development scaffold: a dashboard shell, a working API health endpoint, configuration loading, and a health test. The [messaging service](messaging/README.md) has a Spectrum iMessage echo starter; its backend bridge is still planned. Agent planning, member/task persistence, approval enforcement, and reminders are not implemented yet. No credentials are needed for the starter health check. Settings marked as future in `.env.example` are reserved for later phases.

Never commit `.env` files, actual member phone numbers, inbox contents, recordings, or private transcripts. Only `VITE_` values are exposed to browser code; put provider credentials in the backend environment.
