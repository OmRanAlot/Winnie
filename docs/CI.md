# CI/CD

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## What runs on every pull request

| Check | Runs | Fix it locally |
|---|---|---|
| `backend` | `uv sync --frozen`, `ruff check .`, `pytest` | `cd backend; uv run ruff check . --fix; uv run pytest` |
| `frontend` | `npm ci`, `npm test`, `npm run build` | `cd frontend; npm test; npm run build` |
| `messaging` | `npm ci`, `npm run typecheck`, `npm test` | `cd messaging; npm run typecheck; npm test` |
| `docker-build` | builds `backend/Dockerfile` (not pushed) | `docker build backend` |

Common red checks:
- `uv sync --frozen` fails: you changed `pyproject.toml` without committing the updated `uv.lock` (`cd backend; uv lock`).
- `npm ci` fails: `package.json` and `package-lock.json` disagree; run `npm install` and commit the lockfile.
- `docker-build` fails: the Dockerfile copies something that is not in git (for example gitignored `backend/data/*`).

The checks use no secrets, so they run safely on forks.

## Deploys (push to `main`)

After all four checks pass, `deploy-backend` runs `gcloud run deploy api --source backend` (existing env vars,
secrets and scaling are kept) and then `deploy-frontend` builds the dashboard and runs
`firebase deploy --only hosting`. Each ends with a `/api/health` smoke test. Both are skipped until the
repository variable `GCP_WORKLOAD_IDENTITY_PROVIDER` exists, so CI is useful before deploys are enabled.

Auth is Workload Identity Federation: no JSON key is stored anywhere. Only workflows from this repo on `main`
can deploy.

### Enable deploys (one time)

1. A project owner runs `powershell -File deploy/setup-github-oidc.ps1` (use `-DryRun` first). It prints two values.
2. A repo admin adds repository variables (Settings > Secrets and variables > Actions > Variables):
   `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `VITE_API_BASE_URL` (`/api`), `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_PUBLISHABLE_KEY`. Only public values go here; the Supabase secret key and Gemini key stay in
   Secret Manager (`deploy/set-cloud-run-env.ps1`).
3. Create a GitHub environment named `production` (optionally require a reviewer to approve deploys).

### Block broken pushes to `main` (repo admin)

Settings > Branches > add a rule for `main`: require a pull request, require status checks `backend`, `frontend`,
`messaging` and `docker-build` to pass, and disallow force pushes. Without this rule the checks only warn.

## Not covered yet

Authentication and rate limiting on the API, and deploying `messaging/` (a long-running service; see the deploy notes).
