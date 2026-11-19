# CI and production deployment

`.github/workflows/backend.yml` runs the extended backend, migration, messaging,
and container checks. `.github/workflows/ci.yml` runs the release checks on pull
requests and pushes to `main`. On a push to `main`, with the GitHub OIDC variables
configured, it deploys the API to Cloud Run and the dashboard to Firebase Hosting.
Neither workflow applies Supabase migrations or sends test texts.

The production target is project `hack-princeton-514716`, Cloud Run service `api`
in `us-east1`, and Firebase Hosting at
`https://hack-princeton-514716.web.app`. Firebase rewrites `/api/**` to Cloud Run.
GitHub authenticates through Workload Identity Federation; no GCP key file is
needed in repository secrets.

The main release workflow deploys a zero-traffic Cloud Run revision, gives it a
temporary `ci-candidate` URL, and checks `/api/health` there. Only after that
check passes does it move 100% of API traffic to the new revision. A failed
production smoke test restores the previous serving revision. The frontend
build and Hosting deploy follow the backend promotion. This matters because a
previously pinned Cloud Run revision could let `gcloud run deploy` succeed while
the public URL continued to serve older code.

Check the GitHub Actions run and Cloud Run traffic after each release. The
public health endpoint and Photon webhook readiness endpoint confirm routing
and configuration; a real opted-in phone test is still needed to verify text
delivery. Supabase migration history and Secret Manager values are managed
separately from this workflow.

To reproduce the release checks locally, run `uv run pytest` and `uv run ruff
check .` in `backend/`, then `npm test` and `npm run build` in `frontend/`.
