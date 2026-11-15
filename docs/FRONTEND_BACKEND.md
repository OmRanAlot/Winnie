# Dashboard connections

The signed-in dashboard loads persisted board data. It starts empty while loading and shows
connection errors instead of substituting sample records. Refresh runs every 15 seconds,
when the window regains focus, and after successful writes.
Request-history and dependency errors are reported separately and do not block task
refreshes. The dashboard includes **Refresh tasks** and the last successful task-refresh
time. Background polls skip an in-progress refresh instead of continually superseding it.
Task status controls show **Saving…**, prevent duplicate clicks, and use the backend's
confirmed response immediately. Completing a task removes it from Due Soon and shows
a persistent message with **View task**. Save errors remain visible until dismissed;
refreshing other board data is separate from confirming the write.

Admins start with **All E-board tasks** selected in the Gantt; members start with their
own assignments. The chart remains a weekly view: arrows change the week, the caption
shows scheduled and total counts, and **View all tasks** opens the complete task list.
Sheets changes appear only after a reviewed sync is applied or an enabled sync worker
successfully applies them; previewing a spreadsheet does not update stored tasks.

## Apply the dashboard schema

For an existing project that has the authentication and meeting attendance migrations,
run `supabase/migrations/20261115120000_connect_dashboard.sql` once in the Supabase SQL
Editor. It adds task notes, schedule fields, completion tracking, private administrator
feedback and per-administrator task drafts. Existing tasks, accounts and roster contacts
are preserved. New fields are additive; existing completed tasks keep an unknown
completion timestamp until a later status transition supplies one.

For a new database, apply all migrations in filename order. If using the CLI against an
existing database, first reconcile migration history as described in SCHEMA_UPGRADE.md;
do not blindly push migrations already applied through the SQL Editor.

Restart both development servers in separate terminals from the repository root:

```powershell
Set-Location backend
uv run fastapi dev app/main.py
```

```powershell
Set-Location frontend
npm run dev
```

The frontend uses the Vite proxy for `/api` on port 5173; the backend runs on port 8000.
Supabase session access tokens accompany API calls. Service-role credentials stay in
the backend environment. Login and password setup continue to use Supabase Auth.

## Connected actions

The supplied eboard CSV/TSV files and approved roster/reference data in `backend/data`
are authoritative for board information. They are not demo placeholders. The app reads
the roster imported into Supabase and uses the saved role/skill/history reference files;
it does not automatically re-import these files on each request. Board information is
read-only in the dashboard, including for administrators. A future year's roster is an
intentional import, separate from task synchronization. Task tracker data can change
through Sheets synchronization and application task actions; those updates do not
replace the eboard roster or its reference files.

| Screen or action | Persistence/API |
| --- | --- |
| Dashboard, task summary, status controls | `GET/POST/PATCH /api/tasks/records` |
| Gantt schedule and dependency arrows | Task start/due dates and `GET /api/dashboard/dependencies` |
| Board notes | Task `notes` field, saved independently of its description |
| Manual task creation | Title, description, owner, priority, month, start/due date and time; backend supplies active semester |
| Plan with Winnie | `POST /api/planning/drafts`; suggestions are reviewed before creating a task |
| Save/Resume Draft | `GET/PUT /api/dashboard/draft`, owned by the signed-in administrator |
| Member roster and suggested assignees | `/api/members`, `/api/members/assignments`, `/api/members/candidates/{id}` |
| Board information | Read-only approved roster; profile-edit requests are rejected by the backend |
| Evaluations | `GET/PUT /api/dashboard/evaluations/{code}`; administrator-only feedback |
| Evaluation metrics | Actual loaded tasks, recorded attendance and approved reassignment history; missing history displays as unknown |
| Meeting list, detail and attendance | `/api/meetings` and `/api/meetings/{id}/attendance` |
| Audio upload | Multipart `POST /api/meetings/ingest`, then reload persisted meetings/tasks |
| Browser recording | Save `/api/recordings`, process `/api/recordings/{id}/assignments`, then refresh board |
| Reassignment requests and decisions | Authenticated Supabase RPCs; recipient accepts/denies first, then administrator approval transfers ownership |
| Help review | `/api/help-requests` and its decision endpoint |

Authentication accounts/passwords and operational records (tasks, meetings, attendance,
drafts and evaluation feedback) are separate from the fixed board information. Only
consented contacts are used for account linking and invitations. Sheets task updates
do not change roles, skills, graduation information, contact consent or administrator flags.

Google Sheets synchronization has a separate migration and setup guide in
[GOOGLE_SHEETS_SYNC.md](GOOGLE_SHEETS_SYNC.md).
Messaging bridges, reminder workers and imports remain server-side integrations; they
are not browser endpoints requiring provider secrets.

## Recipient consent for reassignment

Photon and browser requests share this queue after applying
`20261115160000_unify_photon_reassignments.sql` after the recipient-consent migration.
See [the shared workflow and demo test](HELP_WORKFLOW.md) for text commands,
notifications, deployment settings and the recipient/admin test sequence.

Apply `supabase/migrations/20261115150000_reassignment_recipient_consent.sql` once
after the existing reassignment and authentication migrations. Restart the frontend.
The receiving member opens **Requests** to see incoming proposals and **Accept** /
**Deny**. Acceptance saves their response and waits for administrator approval;
denial closes the request without changing ownership. Administrators cannot approve
an unanswered or denied proposal. Existing pending requests also require acceptance;
historical decisions and task owners are preserved.

The `respond_task_reassignment` RPC derives the member from their verified session,
not browser-supplied identity. RLS lets the requester, recipient and reviewers see the
request. Responses are recorded with profile ID and timestamp, can be submitted only
once, and are protected against stale/completed tasks. Existing admin approval still
checks the assignment atomically before transferring it. No external messages are sent.

## Demo verification

After applying the migration and restarting, sign in as an administrator. Create a task
with an assignee and dates, edit its notes, change status and reload the page. Save a
draft, reload, and choose **Resume saved draft** under **Create Task**. Save an evaluation
comment and reopen it. Confirm the board information has no edit controls. Record
attendance and check that the evaluation uses recorded meetings only. A member account should not see administrator
editing controls, and the API also rejects those writes.

Automated checks cover HTTP contracts, role enforcement, UI saves and failure handling,
task creation and note reloads, and the real SQL migration chain using synthetic data.
Live audio/Gemini processing still requires configured provider credentials and a sample
meeting upload; automated tests do not send real recordings or create tasks in the hosted project.
