# Shared event plans and approval

Apply `supabase/migrations/20261115180000_event_plan_approval.sql` after the existing
migrations, then deploy backend and frontend together. Do not replay already-applied
migrations. This migration adds private proposal and notification tables plus task provenance;
it does not modify the board roster or send messages when installed.

Production planning images must install the `agents` extra; the Dockerfile now does so
and checks that the Gemini LangChain provider imports during the build. For Gemini
planning keep `WINNIE_PLANNING_MODE=deepagents` and an accessible
`WINNIE_PLANNING_MODEL=google_genai:<model-id>`. The deployed image does not include local
private planning history; AI mode can draft from the idea with an explicit warning.
Missing provider packages now produce a specific rebuild/deploy error instead of the
generic context/model/credentials message. Do not switch a working model merely because
of that packaging error.

## Administrator flow

1. Open Admin Settings → Plan Event. Generate suggestions or enter an outline manually.
2. Expand tasks to edit titles, owners, deadlines, phases and dependencies. Add structured
   tasks to a manual outline using **Add task to plan**. Owners must be chosen explicitly;
   a suggested role does not silently select a person.
3. Save the draft, then reopen it from Saved Event Plans. All signed-in administrators see
   shared plans across devices. Saving a draft does not create assignments or send texts.
4. Choose **Approve and create tasks** or **Reject plan** on the saved revision. Every task
   needs an active owner and deadline before approval. Save and reopen after edits.
5. Approval creates tasks with stable UUIDs/WIN codes, original owners, plan provenance,
   dependency edges and assignment notification intents in one transaction. Approved plans
   are locked; their tasks appear in the existing dashboard and recipient views. Retrying
   approval of the same revision returns the original result without duplicate tasks/texts.
6. Rejection creates no tasks. Editing a rejected plan saves a new draft revision for review.
   A stale revision produces HTTP 409; reopen the current plan instead of overwriting it.

An outline without structured tasks can be saved but cannot be approved. Dependency cycles,
missing references, impossible dependency dates and event-phase date conflicts are rejected.
Existing browser-only plans remain in localStorage; they are not silently uploaded or deleted.
Copy any older outline into a new shared draft if it should be retained in Supabase.

## API and authorization

- `GET/POST /api/event-plans`: shared administrator list / new draft.
- `GET/PUT /api/event-plans/{uuid}`: read / replace draft with `expected_revision`.
- `POST /api/event-plans/{uuid}/review`: `expected_revision`, `decision` (`approved` or
  `rejected`), optional `note`.

All routes require a signed-in administrator with completed password setup. Shared server
keys cannot impersonate a reviewer. The server-only `manage_event_plan` RPC rechecks the
actor's current verified email, roster consent/activity, password setup and `is_admin` flag.
Browser roles cannot directly access proposal/notification tables or invoke that RPC.
Approval locks the proposal and selected owner rows and records reviewer, time and revision.

Plans retain the active semester from creation. Updating event dates does not silently move
the plan between semesters. Create a new plan for a different board term.

## Photon assignment delivery

Approval queues notification intent atomically, then the browser kicks the existing Photon
Cloud Tasks dispatcher. Queue failure does not undo approved tasks; the UI reports a warning.
Use Requests → Retry text notifications after fixing configuration. The webhook worker also
drains pending notices when processing messages. Existing Photon enablement, bridge and queue configuration must be enabled; this adds
no always-running worker. Plan notices do not require the separate help-workflow flag.

Physical sends require an active consenting member with a verified, opted-in iMessage identity.
Missing identities leave notices pending. Changed owners/completed tasks cancel unsent
assignment notices. Provider acceptance is recorded separately from approval; uncertain sends
are not blindly retried. These are initial assignment texts. Deadline scheduling and dependency-ready notices are
now wired separately through [AUTOMATION.md](AUTOMATION.md).

## Acceptance checks

Save on one device and open from another administrator. Confirm no tasks exist for the draft.
Approve and verify owner, dates, dependencies and WIN codes in the task list. Repeat approval
and verify counts do not change. Test two administrators editing the same revision, rejection,
an inactive owner, unknown dependency and ordinary-member access. With an opted-in test
phone, verify the assignment text arrives and `done WIN-…` updates the task. Automated tests
use synthetic records and mock sends; no real member messages are sent during testing.

Meeting upload/recording extraction still uses its existing immediate-save path. This change
finishes Event Plan persistence and activation; moving meeting extraction through proposals
is a separate pending audit item.
