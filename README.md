# Winnie

An iMessage-first AI coordinator for the NJIT Women in Computing Society, built for HackPrinceton.

Winnie turns meeting context into proposed event plans, asks the President to approve them, and helps members update their tasks with a text.

Start with [CONTEXT.md](CONTEXT.md) for product and implementation decisions and [docs/GAMEPLAN.md](docs/GAMEPLAN.md) for the build sequence and demo checklist.

## Repository

```text
frontend/             React + TypeScript + Vite dashboard
backend/              Python + FastAPI API and future worker
docs/                 Execution plan and API contract
.env.example          Backend settings, including future integration placeholders
frontend/.env.example Public browser settings only
```

## Run locally

Prerequisites: Python 3.11+ and Node.js 22.12+ with npm. Commands below use PowerShell, starting in the repository root.

Backend, terminal 1:

```powershell
Copy-Item .env.example .env
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -e "./backend[dev]"
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Frontend, terminal 2:

```powershell
Copy-Item frontend/.env.example frontend/.env
Set-Location frontend
npm install
npm run dev
```

Open [the dashboard](http://localhost:5173) and [the API docs](http://localhost:8000/docs). The dashboard checks `/api/health` through Vite's local proxy.

On macOS/Linux, use `cp` and `backend/.venv/bin/python` instead of the PowerShell copy command and Windows Python path.

## Checks

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests
npm --prefix frontend run build
```

## What exists today

This is a development scaffold: a dashboard shell, a working API health endpoint, configuration loading, and a health test. Agent planning, member/task persistence, approval enforcement, messaging, and reminders are planned in the linked documents; they are not implemented yet. No credentials are needed for the starter health check. Settings marked as future in `.env.example` are reserved for later phases.

Never commit `.env` files, actual member phone numbers, inbox contents, recordings, or private transcripts. Only `VITE_` values are exposed to browser code; put provider credentials in the backend environment.
