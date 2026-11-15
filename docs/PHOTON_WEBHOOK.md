# Photon without a running laptop

Production uses **Stable Spectrum signed webhooks** on the existing FastAPI service.
There is no additional always-running Photon container or worker pool.

A text arrives at `/api/photon/webhook`. FastAPI verifies the HMAC over the raw bytes,
registered webhook ID and five-minute timestamp tolerance. It stores a private inbox
record in Supabase and submits a Cloud Tasks job, then acknowledges Photon quickly.
Cloud Tasks calls `/api/photon/work` on the same backend with the private bridge secret.
That request runs the existing Gemini/task/reassignment logic and makes one short-lived
outbound SDK call. Node and the pinned official SDK are included in the backend image;
the subprocess closes when the send completes and never subscribes to an inbound stream.

## One-time setup

1. Apply these migrations in Supabase SQL Editor, in order, skipping ones already applied:
   - `20261115150000_reassignment_recipient_consent.sql`
   - `20261115160000_unify_photon_reassignments.sql`
   - `20261115170000_photon_webhook_inbox.sql`
2. Keep the existing Photon `PROJECT_ID` and `PROJECT_SECRET` in `messaging/.env`.
   Keep the backend's existing Supabase/Gemini keys and bridge secret configured on Cloud Run.
3. Install/authenticate Google Cloud CLI on the deployment machine (`gcloud auth login`).
   Use an account authorized to deploy `api`, manage its queue and update its secrets.
   From the repository root run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy/setup-photon-webhook.ps1
   ```

The script deploys the backend including its request-scoped outbound runtime, verifies
that the webhook route exists, registers that URL with the existing Photon project,
and saves the one-time signing secret to the gitignored `backend/.env`.
It creates `winnie-photon` in Cloud Tasks, limits concurrent dispatches to one, and gives
only the API runtime service account enqueue permission on that queue. It uploads the
Photon secrets to Secret Manager, grants that runtime account access to those two
secrets, and updates the existing `api` service's settings. Other API settings are preserved.
The bridge secret must already be set on that service; it is not regenerated.

The Google Cloud CLI is not installed in the current Codex shell. Docker Desktop's
engine was also unavailable during local verification, so the Docker image must be
built by deployment/CI. The sender, webhook, queue and migration tests run independently.

The registered URL is:

`https://hack-princeton-514716.web.app/api/photon/webhook`

To register separately after a backend deployment, run from `backend/`:

```powershell
uv run python -m app.cli.photon_webhook
```

The registration command refuses to register against a missing endpoint and refuses
to overwrite an existing registration whose signing secret is not available locally.
It never prints credentials. Upload the saved values to Cloud Run before enabling delivery.
Registration briefly starts delivery before the secret is deployed; avoid texting during
that setup window. The script does not automatically send a test message.

## Deployed settings

Regular environment variables:

- `WINNIE_PHOTON_ENABLED=true`
- `WINNIE_PHOTON_PROJECT_ID`: the existing Spectrum project ID
- `WINNIE_PHOTON_WEBHOOK_ID`: the registered webhook ID
- `WINNIE_PHOTON_QUEUE=projects/hack-princeton-514716/locations/us-east1/queues/winnie-photon`
- `WINNIE_PHOTON_TASK_URL`: the API service's HTTPS URL ending in `/api/photon/work`
- `WINNIE_MESSAGE_AI_ENABLED=true`
- `WINNIE_HELP_WORKFLOW_ENABLED=true`

Secrets:

- `WINNIE_PHOTON_PROJECT_SECRET`
- `WINNIE_PHOTON_WEBHOOK_SECRET`
- Existing `WINNIE_MESSAGING_BRIDGE_SECRET`, Supabase secret and Gemini key

Do not copy a local Windows credential-file path into Cloud Run. Cloud Tasks uses the
Cloud Run runtime service account via Application Default Credentials.

## Verify with the laptop listener stopped

Stop `npm start` in `messaging/`. Text `ping`, then `whoami`, then `tasks` from a linked
member. Ask a natural-language question about a task. The replies must arrive with
that terminal closed. In Cloud Run logs, expect webhook and work requests, with no
message contents or phone numbers logged. Check the Cloud Tasks queue for retries.

Run the [shared reassignment demo](HELP_WORKFLOW.md): request help, select a candidate,
accept from the receiving member, then approve as administrator. Web and text actions
share the same queue. The frontend queues notification work after a saved action;
**Retry text notifications** under Requests lets an administrator retry a missed queue kick.
In webhook mode, `/api/messages` returns `reply: null` to old stream listeners, and the
old help-notification poll stops claiming deliveries, so a leftover laptop process
cannot duplicate webhook replies or take the new notification jobs.

## Delivery limits and costs

Inbox rows deduplicate deliveries across Cloud Run instances. The worker stores its
reply before sending, fences concurrent claims, and marks a send uncertain if acceptance
cannot be confirmed. It does not blindly resend uncertain physical texts. This favors
avoiding duplicates; inspect the private inbox/outbox before manually retrying a send.
Private inbox data contains message text and sender metadata; restrict database access
and set a retention policy appropriate to the demo (for example, delete completed records
after seven days). No roster files are modified.

Cloud Tasks is request-driven, with no fixed always-on listener charge. Its first one
million billable operations per month per account are currently free; Cloud Run,
network, Gemini and Photon limits still apply. This is not a guarantee of zero charges.
Existing scheduled deadline-reminder generation still needs a scheduler; inbound webhooks
do not run the deadline worker on a timer. New reassignment notifications are event-driven.

Sources: [Stable Spectrum webhooks](https://photon.codes/docs/webhooks/overview),
[delivery/retries](https://photon.codes/docs/webhooks/delivery),
[Cloud Tasks pricing](https://cloud.google.com/tasks/pricing).

Scheduled reminders, Nudge, dependency notices and automatic tracker updates are now wired through [AUTOMATION.md](AUTOMATION.md); apply its additional migrations and configure the scheduler jobs.
