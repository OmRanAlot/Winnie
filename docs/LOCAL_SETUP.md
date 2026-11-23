# Local setup (pre-deploy testing)

Run the API and dashboard on your laptop against the real Supabase project, Gemini key, and Photon project. No Docker or local Postgres is required. This is for testing before you deploy; production still uses Cloud Run and the Photon webhook path described in [PHOTON_WEBHOOK.md](PHOTON_WEBHOOK.md).

**Every command below assumes you are in the repository root** (the folder that contains `backend/`, `frontend/`, `messaging/`, and `scripts/`).

```powershell
Set-Location C:\path\to\Winnie   # once, then stay here
```

Local helper scripts live in `scripts/`:

| Script | Purpose |
|---|---|
| `scripts/dev-local.ps1` | Start backend + frontend (optional Photon listener) |
| `scripts/test-photon.ps1` | Send / listen / chat with Photon using **your** number |

## Prerequisites

| Tool | Notes |
|---|---|
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.13 for the backend |
| Node.js **22.12+** and npm | Frontend and messaging |
| PowerShell | `scripts/*.ps1` are for Windows; macOS/Linux can use the manual commands |
| A Supabase project | Same one the deployed app uses unless you intentionally point elsewhere |
| A Gemini API key | Task extraction and optional message AI |
| A Photon Spectrum project | Only if you will test iMessage |

## 1. Environment files

Never commit `.env` files. Copy the examples once, then fill in secrets from your dashboards.

### Backend (`backend/.env` or repo-root `.env`)

The backend reads both. Either location works; most people use `backend/.env`.

```powershell
Copy-Item .env.example backend\.env
# or: Copy-Item .env.example .env
```

Minimum for a useful local run:

| Variable | Where to get it | Purpose |
|---|---|---|
| `SUPABASE_URL` or `WINNIE_SUPABASE_URL` | Supabase → Project Settings → API | Task store URL |
| `SUPABASE_SERVICE_ROLE_KEY` or `WINNIE_SUPABASE_SECRET_KEY` | Supabase → API → `service_role` secret | Server-side DB access (never put this in the frontend) |
| `GEMINI_API_KEY` | Google AI Studio / Gemini | Meeting → tasks and message AI |
| `WINNIE_MESSAGING_BRIDGE_SECRET` | Generate locally (see below) | Authenticates the Photon laptop listener |
| `WINNIE_PHOTON_PROJECT_ID` / `WINNIE_PHOTON_PROJECT_SECRET` | [Photon dashboard](https://app.photon.codes) | Same as messaging `PROJECT_ID` / `PROJECT_SECRET` |
| `WINNIE_PHOTON_ENABLED` | Set to `false` for laptop testing | `true` is for Cloud Run webhook mode |

Generate a bridge secret once (still from the repo root):

```powershell
uv --directory backend run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the **same** value into:

- `WINNIE_MESSAGING_BRIDGE_SECRET` in `backend/.env`
- `MESSAGING_BRIDGE_SECRET` in `messaging/.env`

For laptop Photon replies, keep:

```dotenv
WINNIE_PHOTON_ENABLED=false
```

If this is `true`, the local listener gets `reply=null` because production webhook mode owns inbound messages.

Apply Supabase migrations if you have not already (SQL Editor in filename order, or `npx supabase db push`). See the Task store section in [README.md](../README.md).

### Frontend (`frontend/.env`)

```powershell
Copy-Item frontend\.env.example frontend\.env
```

| Variable | Notes |
|---|---|
| `VITE_API_BASE_URL` | Leave as `/api` so Vite proxies to `http://localhost:8000` |
| `VITE_SUPABASE_URL` | Same project URL as the backend |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Supabase **publishable / anon** key only — never the service-role key |

### Messaging (`messaging/.env`) — Photon only

```powershell
Copy-Item messaging\.env.example messaging\.env
```

| Variable | Notes |
|---|---|
| `PROJECT_ID` | Photon Spectrum project id |
| `PROJECT_SECRET` | Photon project secret |
| `MESSAGING_BRIDGE_SECRET` | Must match `WINNIE_MESSAGING_BRIDGE_SECRET` |
| `BACKEND_URL` | `http://localhost:8000` (or `http://127.0.0.1:8000`) |

`.\scripts\test-photon.ps1` and `.\scripts\dev-local.ps1 -Messaging` will also accept `WINNIE_PHOTON_*` and `WINNIE_MESSAGING_BRIDGE_SECRET` from `backend/.env` if `messaging/.env` is incomplete.

## 2. Start the stack

### One command (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -Messaging
powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -SkipInstall
powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -FrontendPort 5174 -BackendPort 8000
```

| Flag | Effect |
|---|---|
| *(none)* | Backend (`--local`) + frontend |
| `-Messaging` | Also starts the Photon laptop listener |
| `-SkipInstall` | Skip `uv sync` / `npm install` on later runs |
| `-BackendPort 9000` | Change the API port (default `8000`) |
| `-FrontendPort 5174` | Change the Vite dashboard port (default `5173`) |

What you get:

| URL | What |
|---|---|
| http://localhost:5173 | Dashboard (or whatever `-FrontendPort` you set) |
| http://localhost:8000/docs | FastAPI docs (or your `-BackendPort`) |
| http://127.0.0.1:8000 | API (local mode binds loopback only) |

Ctrl+C stops every process the script started. The backend log must say `mode=local`. If it says `mode=prod`, it was started without `--local`.

Outside services (Supabase, Gemini, Photon) use whatever your `.env` files point at — the same as production unless you use a separate Supabase project.

### Manual (any OS, still from repo root)

Terminal 1 — backend:

```powershell
uv --directory backend sync
uv --directory backend run python -m app.cli.serve --local
# optional: ... serve --local --port 9000
```

Terminal 2 — frontend:

```powershell
npm --prefix frontend install
npm --prefix frontend run dev:local -- --port 5173 --strictPort
```

Terminal 3 (optional) — Photon listener:

```powershell
npm --prefix messaging install
npm --prefix messaging start
```

## 3. Test Photon with your own number

Do **not** use e-board roster numbers from Supabase for this. Pass **your** phone or iMessage email on the command line. Shared Photon lines only text people allowlisted under **Users** in the project.

### One-time Photon allowlist

1. Open [app.photon.codes](https://app.photon.codes) → your Winnie project → **Users**.
2. Add the phone number or email your iMessage is linked to (E.164 like `+15551234567`, or an email handle).
3. Confirm `PROJECT_ID` / `PROJECT_SECRET` (or `WINNIE_PHOTON_*`) are set as above.
4. Keep `WINNIE_PHOTON_ENABLED=false` while testing on the laptop.

### CLI commands (repo root)

```powershell
# Show usage
.\scripts\test-photon.ps1 help

# Bot -> your phone
.\scripts\test-photon.ps1 send -To +1YOURNUMBER -Text "hello from Winnie"

# Print inbound texts from your phone
.\scripts\test-photon.ps1 listen -From +1YOURNUMBER

# Interactive: type in the terminal to send; see replies from your phone
.\scripts\test-photon.ps1 chat -To +1YOURNUMBER

# Same, but forward inbound DMs to the local API and text Winnie's reply back
.\scripts\test-photon.ps1 chat -To +1YOURNUMBER -Bridge
```

Equivalent npm form (also from repo root):

```powershell
npm --prefix messaging run test:photon -- send --to +1YOURNUMBER --text "hello from Winnie"
npm --prefix messaging run test:photon -- listen --from +1YOURNUMBER
npm --prefix messaging run test:photon -- chat --to +1YOURNUMBER --bridge
```

### Full listener path (phone → Winnie → phone)

1. Start the stack with messaging:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -Messaging
   ```

2. Text the **project iMessage line** shown in the Photon dashboard from your allowlisted phone.
3. Try:

| You text | Expected |
|---|---|
| `ping` | Connection check (no member link required) |
| `help` | Menu |
| `whoami` | Shows your Photon sender id / link status |
| `tasks` | Your tasks only after you register that sender in Supabase (see [MESSAGING_MEMBERS.md](MESSAGING_MEMBERS.md)) |

Personal task commands need a `members` + `member_identities` row for **your** sender id. That is separate from the Photon allowlist and is documented in the messaging members guide. `ping` works before that.

Run only **one** inbound listener at a time (`scripts\dev-local.ps1 -Messaging` **or** `scripts\test-photon.ps1 listen/chat`, not both fighting the same stream).

## 4. Sanity checklist

- [ ] `backend/.env` has Supabase service-role + `GEMINI_API_KEY`
- [ ] `frontend/.env` has publishable key only (no service-role)
- [ ] Backend startup log shows `mode=local`
- [ ] http://localhost:5173 loads; http://localhost:8000/docs opens
- [ ] `GET /api/health` succeeds
- [ ] For Photon: Users allowlist includes you; `WINNIE_PHOTON_ENABLED=false`; bridge secrets match
- [ ] `.\scripts\test-photon.ps1 send -To +1YOU -Text "hi"` delivers to your phone

## 5. Common failures

| Symptom | Likely fix |
|---|---|
| Tasks API 503 | Missing Supabase URL / service-role key, or migrations not applied |
| Task extraction fails | Set `GEMINI_API_KEY` |
| Messaging HTTP 401 | Bridge secrets do not match between backend and messaging |
| Photon “Target not allowed” | Add your number under Photon → Users |
| Listener gets no useful reply / `reply=null` | Set `WINNIE_PHOTON_ENABLED=false` for laptop testing |
| Port already in use | Stop the old stack (Ctrl+C on `scripts\dev-local.ps1`, or `taskkill` the process on 8000/5173) |
| Scripts blocked by execution policy | `powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1` |

## Related docs

- [MESSAGING_MEMBERS.md](MESSAGING_MEMBERS.md) — link a Photon sender to a member for `tasks` / `whoami`
- [PHOTON_WEBHOOK.md](PHOTON_WEBHOOK.md) — production delivery without a laptop listener
- [FRONTEND_BACKEND.md](FRONTEND_BACKEND.md) — dashboard ↔ API contract
- [README.md](../README.md) — repo map and Supabase migration steps
