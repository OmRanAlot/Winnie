# Deadline reminders and delivery deduplication

Reminder timing is deterministic; no Gemini call decides whether to send a deadline
reminder. The backend scans canonical unfinished tasks in the active semester. The
existing Photon listener polls the backend's persistent outbox and sends authorized
direct messages. Both programs must be running for automatic delivery.

## Default schedule

| Reminder | Local time in America/New_York |
|---|---|
| Seven days before the deadline | 9:00 AM |
| Three days before the deadline | 9:00 AM |
| Previous evening | 6:00 PM |

Task deadlines are date-only. Local calendar-day arithmetic handles daylight saving
changes. A reminder remains eligible until the next stage; the previous-evening stage
expires at the start of the due date. A late scan sends only the current eligible
stage, not a burst of every missed reminder. Text states the actual due date rather
than an inaccurate countdown after a delayed send.

If the task was created after a stage's scheduled time, that stage is skipped. Editing
its due date or assignment starts a new reminder schedule and cancels pending old
deliveries. Completed and undated tasks do not generate reminders. Unrecognized or
ambiguous assignment cells are skipped rather than guessed.

## 1. Apply the migration

Run `supabase/migrations/20261114180000_deadline_reminders.sql` once in the project's
SQL Editor, after the existing task/member migrations. It adds:

- `reminder_deliveries`: a durable, private outbox and delivery receipts.
- `member_identities.reminders_enabled`: defaults to false. A member can have only
  one enabled reminder destination, avoiding duplicate texts to phone and email.
- `tasks.reminder_schedule_started_at`: tracks schedule resets after deadline or
  assignment changes. Existing tasks are initialized from their creation time.
- Server-only queue/claim/begin/result functions and a cancellation trigger.

Installing the migration does not send messages. Task status, titles and deadlines
are preserved; backfilling schedule metadata updates task modification timestamps.

## 2. Select a test recipient and preview

Use a registered, opted-in test member. In Table Editor -> `member_identities`, set
`reminders_enabled = true` on exactly one of their verified identities. Keep the
member active and their semester aliases configured. Other identities remain false.

From `backend/`, preview eligibility without queue writes:

```powershell
& ".\.venv\Scripts\python.exe" -m app.reminder_worker
```

`eligible: 0` can be correct: no current reminder window, an undated/completed task,
late task creation, no enabled recipient, or unresolved aliases. Do not change real
deadlines merely to make a reminder appear. Tests use fictional tasks and clocks.

## 3. Exercise the persistent mock outbox

Backend environment settings (root `.env`, or `backend/.env` if used):

```dotenv
WINNIE_REMINDERS_ENABLED=false
WINNIE_REMINDER_TRANSPORT=mock
WINNIE_REMINDER_TIMEZONE=America/New_York
WINNIE_REMINDER_DAYTIME_HOUR=9
WINNIE_REMINDER_EVENING_HOUR=18
```

An explicit one-cycle mock run queues due reminders and records simulated delivery:

```powershell
& ".\.venv\Scripts\python.exe" -m app.reminder_worker --once
& ".\.venv\Scripts\python.exe" -m app.reminder_worker --status
```

Run it twice: the second run must not repeat the mock deliveries. Inspect
`reminder_deliveries` in Supabase for `mock_sent`, `cancelled`, `uncertain`, or `failed`.
Mock and real receipts have separate deduplication keys, so a mock test is never
represented as a real send or used to suppress a later real delivery.

For a labeled demo, `--at 2027-01-13T14:00:00Z` injects a timezone-aware clock into
preview/mock operations. This flag is rejected when transport is Photon. It never
changes the operating system clock. The CLI cannot send real reminders.

## 4. Enable automatic delivery

After the mock checks, choose the backend transport and enable polling:

Backend `.env`:

```dotenv
WINNIE_REMINDERS_ENABLED=true
WINNIE_REMINDER_TRANSPORT=photon
```

`messaging/.env`:

```dotenv
REMINDER_POLL_ENABLED=true
BACKEND_URL=http://localhost:8000
```

Preserve the matching bridge secrets and existing Photon credentials. Restart both
programs. The listener polls approximately every minute while idle and drains up to
20 deliveries sequentially per cycle. The backend checks the active member, preferred
identity, current assignment, current deadline, expiry and task status before release.
Real recipients must also be allowed in the Photon project. Disable either the backend
reminder flag or polling flag to stop new deliveries; acknowledgements remain accepted.

For automatic mock operation instead, use `WINNIE_REMINDERS_ENABLED=true` with transport
`mock`; the backend records simulated deliveries and returns no live payload to Photon.

Keep the listener running as an always-on worker when deploying. A host that suspends
background work needs a worker/scheduler arrangement; merely hosting the API does not
run the polling loop. No deployment changes are included in this feature.

## How duplicate prevention works

Each record is unique by task, member, deadline, reminder stage and transport. A scan
may refresh a pending record, but cannot recreate a sent or uncertain one. Atomic
database claims with tokens and leases prevent two workers from taking the same send.
After assignment checks, the record moves from `claimed` to `sending` before a payload
is returned to the listener. A repeated request cannot release that same payload again.

The listener sends once and retries only acknowledgement requests (up to three times).
An acknowledgement records the provider message ID. `sent` means Photon accepted the
send; it is not proof of handset delivery or reading. Mock results use `mock_sent`.

An expired claim that never began sending can be recovered up to three claims. Its old
claim token becomes invalid. Exhausted claims are visible as `failed`. If the process
crashes or a send times out after entering `sending`, the row becomes `uncertain` after
its lease expires. A delayed success acknowledgement can still resolve it to `sent`.
Uncertain sends are **not automatically retried**: Photon may already have accepted
them. Inspect the provider/outbox before any manual recovery. A 20-second send deadline
keeps a hanging provider request from stopping all future reminder cycles.

Exactly-once delivery across a database and an external messaging service cannot be
promised without provider-side idempotency. This implementation chooses not to risk a
second text when the first outcome is unknown, so some uncertain reminders may require
manual resolution or may be missed. Neither an uncertain send nor a mock send is
silently reported as delivered.

Completion, deadline edits and assignment edits cancel queued/claimed obsolete sends.
Revoked destinations and inactive members are checked again before dispatch. A message
already in flight cannot be retracted by completing its task. Task deletion also removes
its outbox rows via the foreign key.

## Code and verification

- `backend/app/services/reminders.py`: injectable clock, schedule, ownership and orchestration.
- `backend/app/integrations/reminders.py`: persistent queue adapter.
- `backend/app/routes/reminders.py`: authenticated internal next/result endpoints. Callers
  cannot supply arbitrary recipients, bodies or a fake clock.
- `backend/app/reminder_worker.py`: read-only preview, mock cycle and status counts.
- `messaging/src/reminders.ts`: polling and acknowledgement handling.
- `messaging/src/index.ts`: actual Photon DM adapter.

```powershell
# backend/, synthetic data only
& ".\.venv\Scripts\python.exe" -m pytest tests/test_reminders.py -q

# repository root, actual migrations in local PostgreSQL/PGlite
node --test supabase/tests/reminders.test.mjs

# messaging/
npm run typecheck
npm test
```

Tests cover schedule boundaries, short-notice creation, daylight saving changes,
repeat scans, competing claims, stale tokens, crash recovery, uncertain outcomes,
completion/deadline cancellation, revoked identities, permission denial, mock isolation,
and retrying acknowledgements without sending again. Hosted migration application and
an opted-in live reminder smoke test remain rollout steps. This does not yet queue
approved-plan assignment notices or dependent-owner notifications.
