# Five-day check-ins and approved ownership transfers

The reminder schedule is now 14 days, 7 days, a 5-day help check-in, 3 days, and the
previous evening. The five-day text asks whether the owner wants replacement suggestions.
`member_skills.py` supplies role-derived skills, while `task_matching.py` recommends
people using those skills and real workload. These are role requirements, not independently
verified personal abilities. Gemini suggests candidates; it cannot approve or execute a transfer.

## Setup

Apply these migrations **once, in order** in Supabase SQL Editor, after existing
task/member/completion migrations:

1. `20261114180000_deadline_reminders.sql` (skip if already applied).
2. `20261114190000_help_checkin_schedule.sql`.
3. `20261114200000_help_handoffs.sql`.

They add reminder stages, private help requests, delivery records, and guarded SQL
functions. A migration changes the database structure; it does not start the app or send texts.
The second migration replaces a check constraint (the allowed reminder names), not task rows.
Do not rerun the original task-creation migration.

In `members`, mark only designated administrators `messaging_admin = true`. This is
separate from the dashboard's visual admin toggle. Every texting participant needs a
verified `member_identities` link. For outgoing messages, set `reminders_enabled = true`
on exactly one iMessage identity per member, including administrators and replacements.
Members must be active. The replacement also needs a verified alias for the active semester.

If skills have not been generated/shared yet, from `backend/`:

```powershell
& ".\.venv\Scripts\python.exe" -m app.services.member_skills --apply
```

That command uses Gemini to propose skills from the roster's role text and saves them
to Supabase. Existing saved skills are reused by the recommendation workflow.

After the migrations, configure `backend/.env` (or the root `.env`; backend values win):

```dotenv
WINNIE_HELP_WORKFLOW_ENABLED=true
WINNIE_HELP_GROUPS_ENABLED=false
WINNIE_HELP_ADMIN_API_KEY=your_private_operator_key
```

Use a real private random value for the operator key. It is entered into the admin
review screen, kept in browser memory, and checked by the backend. Never put it into
a `VITE_` variable or commit it. This is operator-key authentication, not member login.
Keep the existing Gemini credentials and messaging bridge secret.

For admin text notifications, in `messaging/.env`:

```dotenv
HELP_POLL_ENABLED=true
```

Automatic five-day check-ins also require the [reminder settings](REMINDERS.md).
`WINNIE_MESSAGE_AI_ENABLED=true` enables natural-language completion interpretation.
Help notifications are real Photon actions, not simulated by `reminder_worker --once`.
They remain disabled until explicitly configured above.

Restart the backend and listener after changing environment files:

```powershell
# Terminal 1, from the repository root
cd backend
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2, from the repository root
cd messaging
npm start
```

## What people text

Use the actual codes returned by Winnie; these are examples:

| Person | Text | Result |
|---|---|---|
| Owner | `help WIN-202610-1` | Saves a request and returns up to three replacement suggestions. |
| Owner | `yes` after a check-in | Works only for one valid check-in actually sent within the last 12 hours; multiple offers require a task code. Mock reminders never count. |
| Owner | `choose HELP-1 WICS_EXAMPLE` | Selects one saved candidate and asks admins for approval. |
| Admin | `approve HELP-1 v2` | Approves that exact request version and transfers ownership. |
| Admin | `deny HELP-1 v2` | Denies it without changing ownership. |

No response or elapsed time is approval. A bare `yes` never authorizes an admin decision.
Task edits invalidate stale requests. Approval replaces the requesting owner's assignment,
preserving any other co-owners; it does not just add a helper. The local tracker CSV/Google
Sheet is not rewritten: the transfer changes canonical Supabase task data. A later tracker
import can change that assignment again, so review its preview before applying it.

In the dashboard, **Review Pending Task Re-assignments** loads the same pending requests
with the private operator key and provides real Approve/Deny buttons. The existing member
profile screen directs requests to verified iMessage; the website has no authenticated member
request flow yet. Admin alerts appear on the next listener poll (up to about a minute).
If no eligible admin destination exists, the dashboard still shows the pending request.

## Group chats: current Photon limitation

The currently configured Photon project uses a **shared number**. Spectrum's installed
iMessage provider explicitly rejects creating multi-person chats in shared mode. Therefore
keep `WINNIE_HELP_GROUPS_ENABLED=false`. Ownership can transfer after approval, but the
handoff remains `approved_group_pending`; no group creation is attempted.

The adapter for creating the original owner + new owner + Winnie group is implemented,
but has only been tested with synthetic provider responses. After obtaining and verifying
a group-capable dedicated connection, enable `WINNIE_HELP_GROUPS_ENABLED=true`. Existing
approved handoffs will become eligible for group creation; review them first. No upgrade,
number purchase, real group creation, or real notification was performed during implementation.
An existing shared-number group is not automatically bound to a request in this version.

Successful group creation saves the provider's group ID. Only that registered group and its
two verified participants enter the handoff handler; unrelated groups are ignored.
Gemini receives only the group's one task. The new owner can report completion in natural
language or use `done WIN-202610-1`; the original owner cannot complete the transferred task.
The usual ownership, exact-evidence and database checks still apply.

Either participant can send `update Waiting for room confirmation` to notify admins.
Common progress/blocker phrases such as “stuck,” “waiting for,” “booked,” and “submitted”
also queue an admin update. This is a small deterministic phrase detector, not a general
Gemini summary of all chat activity. Confirmed completion notifications come from saved task
state. Admins receive relevant update text, not a copy of every chat message.

## Delivery records and verification

`help_notifications` is an outbox: saved work waiting for the listener to deliver it.
`task_help_requests` records the selected replacement, request version, decision and group ID.
`task_help_request_messages` and `help_group_messages` deduplicate incoming events.
All are server-only with row-level security enabled.

Each outgoing action is claimed once. A crash/timeout after claiming becomes `uncertain`,
not an automatic retry; an operator must reconcile it with Photon. An acknowledgement can
be retried without repeating the physical send or group creation. This favors avoiding
duplicates over guaranteed delivery and does not promise exactly-once delivery across services.
A provider receipt confirms acceptance, not that somebody read the message.

Run isolated checks without sending texts or writing to hosted Supabase:

```powershell
# From backend/
& ".\.venv\Scripts\python.exe" -m pytest tests/test_help_workflow.py tests/test_reminders.py tests/test_conversation.py tests/test_skills_matching.py -q
```

```powershell
# From repository root: local PostgreSQL-compatible test database
node --test supabase/tests/reminders.test.mjs
```

```powershell
# From messaging/
npm test
npm run typecheck
```

The tests cover reminder windows, ambiguous replies, saved candidate selection, admin-only
transfers, version checks, co-owner preservation, group task isolation, and uncertain deliveries.
The live Photon group flow remains unverified until a supported connection is available.
