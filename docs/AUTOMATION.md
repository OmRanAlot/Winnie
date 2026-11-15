# Cloud reminders, notifications and automatic Sheets sync

The existing Cloud Run API performs scheduled scans through two Cloud Scheduler HTTP jobs;
Photon sends through the existing request-driven Cloud Tasks queue. No laptop process or
always-running worker is required once deployment/setup is complete.

## Enable in the hosted project

1. Apply any missing earlier migrations, then apply these new migrations in order:
   - `20261115195000_admin_first_reassignment.sql`
   - `20261115200000_notification_automation.sql`
   Do not replay migrations already installed through the SQL Editor.
2. Ensure the signed Photon webhook/queue setup is working. Keep the local listener stopped.
3. From the repository root, on your partner's computer/account with authorized gcloud access:

   ```powershell
   powershell -File .\deploy\setup-automation.ps1 -EnableSheetsAutoApply
   ```

   The flag explicitly enables auto-apply for the tracker sources already configured on
   Cloud Run. Omit it to preserve each source's existing `auto_apply` setting. Conflicting edits
   still block application and require review in Google Sheets Sync.
4. Deploy the frontend using the normal Firebase deployment. Open Admin Settings →
   Automation and notifications; check job outcomes after the next five-minute tick.

The setup script checks the migration, deploys the existing API, verifies Photon readiness,
creates a scheduler-only service account, grants invocation on this service, preserves existing
secrets/environment values, and creates/updates two jobs. It does not run the jobs immediately.
It does not copy a Windows credentials-file path to Cloud Run. Google Sheets uses the existing
runtime service account and workbook sharing; Scheduler's account only invokes the API.

Two scheduler jobs consume two of the billing account's three free Scheduler jobs. Additional
jobs are currently $0.10/job/month; Cloud Run/Tasks/provider usage can still be billed. See
[Google's pricing](https://cloud.google.com/scheduler/pricing). This setup creates no always-on
container. Existing free allowance usage depends on the account's other projects.

## What is wired

- **Nudge**: admin-only backend action targeting verified current assignees. Deduped once per
  task/recipient per New York calendar day. No free-form recipient or message comes from the
  browser. The UI distinguishes queued, already requested, unavailable recipient and queue failure.
- **Deadline scans**: every five minutes, reusing the existing 14/7/5-help/3-day and previous-
  evening schedule with local calendar arithmetic and persistent dedupe. Missed earlier stages
  are not blasted as catch-up messages. Disabled flags perform no scans.
- **Overdue notices**: at most one per task/recipient/local day, after the due date/time;
  date-only tasks use 5 PM ET. Due-time or assignment changes invalidate stale delivery intent.
- **Initial assignments**: new assigned task records queue a notice. Event-plan approval retains
  its existing atomic plan outbox, so it does not also enqueue a duplicate generic assignment.
  Existing historical tasks are not backfilled with initial-assignment texts by the migration.
- **Dependencies**: completing a prerequisite queues notices only for dependent-task owners and
  only when every prerequisite is done. Scheduled reconciliation handles concurrent completions.
  Reopening a prerequisite invalidates stale readiness. The rest of the board is not messaged.
- **Sheets**: every five minutes, only sources marked `auto_apply=true` are read/applied using
  the existing three-way merge and revision checks. Local changes are preserved; conflicts
  block writes and appear in automation status. Manual sources are skipped completely.
- **Recovery/status**: the reminder tick also kicks pending plan/reassignment/task notices in
  case a browser's original kick failed. Admins can inspect latest run states and queue counts,
  and use Requests → Retry text notifications. A queue failure never undoes a saved task/nudge.

Task notices and scheduled reminders are delivered from 9 AM up to 8 PM in the configured
reminder timezone (default America/New_York). After-hours nudges wait. Interactive replies and
plan/reassignment decisions retain their existing immediate delivery behavior. Default flags
remain disabled in the example environment; the setup script enables cloud notifications,
reminders and Photon transport after readiness checks.

## Environment and authentication

Regular Cloud Run environment variables (no new email or provider API is created):

```dotenv
WINNIE_NOTIFICATIONS_ENABLED=true
WINNIE_REMINDERS_ENABLED=true
WINNIE_REMINDER_TRANSPORT=photon
WINNIE_REMINDER_TIMEZONE=America/New_York
WINNIE_SCHEDULER_SERVICE_ACCOUNT=winnie-scheduler@PROJECT.iam.gserviceaccount.com
WINNIE_SCHEDULER_AUDIENCE=https://YOUR_EXISTING_API.run.app
```

`WINNIE_SHEET_SYNC_SOURCES` is regular environment JSON. Provider keys, Supabase backend key
and the Photon bridge secret remain existing secrets. Only use server values for secrets.

Scheduler calls `/api/internal/automation/reminders` and `/api/internal/automation/sheets` with
Google-signed OIDC tokens. The app verifies signature, audience and the exact verified scheduler
email; Supabase login tokens and browser admin status cannot invoke scheduled jobs. This uses
[Google's HTTP target authentication](https://docs.cloud.google.com/scheduler/docs/http-target-auth).
Each runner has a durable five-minute lease to prevent overlap. Failures return retryable errors;
Sheets conflicts are recorded for human review rather than overwritten. The API does no
background polling and Cloud Run may scale to zero between requests.

## Delivery correctness and testing

Every actual send rechecks current task/assignment and active, consenting, opted-in messaging
identity. Unknown/ambiguous co-owner aliases fail closed. Pending notices for completed,
changed or obsolete tasks are cancelled. Stable notification IDs are passed to Photon; accepted
sends store a provider receipt. Uncertain sends are not automatically repeated. “Sent” means
provider acceptance, not proof the person read the text.

Nudges require a signed-in app administrator and a linked opted-in assignee. SQL queue tables,
claims and scheduler leases are inaccessible to anonymous/authenticated browser database roles.
Original-assignee and completed-transfer history are unaffected by notifications or Sheets sync.

After deployment, test a disposable task, repeat Nudge and verify only one notice, revoke consent
before delivery and verify no send, complete prerequisites and inspect only the dependent owner,
change a deadline and verify stale notices cancel, then test a Sheets conflict and clean apply.
Stop the laptop listener and confirm Scheduler's run timestamps keep advancing. No real texts,
cloud jobs, hosted schema writes or deployments are performed by the automated tests.
