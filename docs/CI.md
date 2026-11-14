# Backend CI and image delivery

`.github/workflows/backend.yml` runs on every pull request, push, merge queue,
and manual dispatch. It deliberately has no path filters, so the required status
is always reported, including when shared schemas or dependencies change.

The workflow runs:

- Python 3.13 with locked uv dependencies, Ruff, and the complete pytest suite.
  Coverage XML and JUnit results are retained as artifacts for 14 days, including
  on test failures. Coverage is reported without an arbitrary minimum threshold.
- Every `supabase/tests/*.test.mjs` migration test against isolated PGlite databases.
- Messaging TypeScript checks, tests, and build with locked npm dependencies.
- A production Docker build and a real `/api/health` request without credentials.

Tests use synthetic data and mocks; no Supabase, Gemini, or Photon secrets are
needed. CI never applies migrations to a hosted database or sends messages.

In GitHub repository Settings → Rules → Rulesets, require **Backend checks**
before merging into the default branch. That aggregate check fails if any job
fails or is cancelled. Enable GitHub Actions if it is disabled for the repository.

After all checks pass on a push to the default branch, the workflow publishes
`ghcr.io/<owner>/<repository>/backend:<full-commit-sha>` and `:latest` using the
automatic GitHub token. Names are lowercased for registry compatibility. The
repository must allow Actions to write packages. Pull requests cannot publish.
Use the commit tag for deployments and rollback.

This provides continuous integration and container delivery. Production rollout
is not configured: the repository has Docker/Cloud Run instructions but no
selected deployment project, service, region, or deployment identity. Configure
that target and its credentials before adding a rollout job after `publish`.
The backend README describes the current manual Cloud Run deployment procedure.

To reproduce checks locally:

```sh
cd backend
uv sync --locked --group dev
uv run --no-sync ruff check .
uv run --no-sync pytest --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml --junitxml=test-results.xml
cd ..
npm ci
node --test supabase/tests/*.test.mjs
npm --prefix messaging ci
npm --prefix messaging run typecheck
npm --prefix messaging test
npm --prefix messaging run build
docker build -t winnie-backend:local backend
```
