# Implementation audit — November 15, 2026

Compared `CONTEXT.md`, `docs/GAMEPLAN.md`, feature guides, frontend entry points and services,
backend routers/services, migrations, Dockerfile and CI workflows. This is a code review and
automated-check audit, not a completed live multi-user acceptance test.

## Current architecture

The project now uses Supabase, Firebase Hosting and Cloud Run. The older plan's Cosmos,
fictional 12-member roster and placeholder dashboard descriptions are stale. The approved
board roster remains authoritative; do not replace it with seed fixtures or re-import contacts
without consent. Synthetic test fixtures are separate from production roster data.

Public read-only checks on November 15 returned:

- `/api/health`: HTTP 200, `status: ok`.
- `/api/photon/webhook`: HTTP 200, `enabled: true`, `configured: true`.

Photon readiness flags do not prove successful queue execution, provider delivery, sender
linking, or the hosted database's complete migration history. A phone test is still required.

## Frontend connection inventory

| Component / action | Connection | Assessment |
| --- | --- | --- |
| Login, invitation password setup, recovery | Supabase Auth; `GET /api/auth/me` | Connected. Invitation CLI default now uses deployed callback. Supabase redirect allowlist and email delivery remain live configuration. |
| Dashboard, task list, Gantt, status and notes | `/api/tasks/records`; `/api/dashboard/dependencies` | Connected, polling and write-error handling present. Task authorization needs tightening below. |
| Profiles, skills, history, suggestions | `/api/members`, `/assignments`, `/candidates/{id}` | Connected. Local reference-file fallbacks are absent from production image; verify shared data completeness. Board information is intentionally read-only. |
| Requests: propose, accept/deny, approve/reject | Authenticated Supabase RPCs plus `/api/photon/dispatch` | Connected with SQL consent/approval enforcement. General task PATCH bypass is fixed in source; deploy the task-permission update. |
| Attendance | `/api/meetings`, create and attendance PATCH | Connected; administrator writes enforced. |
| Evaluations | `/api/dashboard/evaluations/{code}` | Connected; administrator feedback persisted, metrics computed from loaded records. |
| Sheets preview/apply | `/api/sheet-sync/sources`, preview and apply | Connected; reviewed apply is separate from preview. The authenticated scheduled runner is implemented; run setup-automation.ps1 after migration/deployment. |
| Audio upload | `/api/meetings/ingest` | Connected, creates tasks immediately rather than the planned approval stage. |
| Browser Recorder | `/api/recordings`, `/{id}/assignments` | Connected, but file storage and success reporting need fixes below. |
| Plan Event generation | `/api/planning/drafts` | Connected to simple draft generation; staged runs/review API is not used by this screen. |
| Save/reopen/review event plan | `/api/event-plans` | Fixed in source: shared Supabase drafts, revisions, approval/rejection and atomic task/dependency/notice creation. Apply the event-plan migration and deploy. |
| Manual task creation / saved task draft | Backend endpoints exist | Current App imports creation/draft helpers but has no creation call or reachable task form. Leftover resume branch refers to undefined `openTaskCreator`. Earlier connection documentation overstates this feature. |
| Nudge | `/api/notifications/tasks/{id}/nudge` | Fixed in source: admin-authorized daily-deduped notices, queued through Photon with failure reporting. Requires automation migration/setup. |
| HelpReview | Legacy component and decision API | Imported but not rendered; old transfer decisions are disabled in favor of canonical Requests. Remove or redirect stale UI. |
| FairyLights, CursorFx, PlanLoading | Presentation only | No backend connection needed. |

## Prioritized work

1. **Task permissions fixed in source; deployment required.** Both PATCH routes now share
   an assignment policy: members edit only status/notes on verified active-semester tasks;
   administrators may edit metadata and status, but ownership edits require reassignment.
   Writes fence against concurrent task changes using `updated_at`. Regression tests cover
   crafted requests, co-assignees, stale ownership and both status routes. Frontend controls
   reflect ownership, with the API retaining authority. Deploy before treating the live issue
   as resolved. No additional database migration is needed.
2. **Event proposals and approval fixed in source; migration/deployment required.** Shared
   Supabase drafts and exact-revision review now replace browser-only storage. Approval
   atomically creates tasks, dependencies, review audit and assignment notices. Approved
   plans are locked and repeated approval is idempotent. Apply `20261115180000_event_plan_approval.sql`
   and deploy both services; see EVENT_PLAN_APPROVAL.md. General manual task creation
   outside an event plan remains a separate UI gap.
3. **Bring meeting extraction into that review flow.** Both audio paths currently store extracted
   tasks immediately. This contradicts the plan's “drafts never become assignments before
   approval.” The Recorder header still describes review-only behavior incorrectly.
4. **Fix Recorder's saved-success handling.** `assignRecordingTasks` discards `meta.stored` and
   `meta.store_error`; Recorder labels returned proposals “Tasks saved” even when persistence
   failed. Preserve that metadata, report unsaved results and provide retry/download recovery.
5. **Make hosted storage durable.** Audio/recording JSON is on the container filesystem;
   save and assignment extraction are separate HTTP requests. A subsequent instance may not
   have the file. Use private shared object storage with access controls and retention.
   Planning runs use SQLite and FastAPI BackgroundTasks: move these to shared persistence
   and durable execution before claiming hosted restart-safe pause/resume.
6. **Notifications and scheduling implemented; hosted setup required.** Nudge, new-assignment
   notices, dependency-ready notices, scheduled deadline scans, daily overdue notices and
   auto-apply Sheets scans are wired. Admin Settings exposes job/queue status. Apply the
   admin-first and automation migrations and follow AUTOMATION.md on the authenticated
   deployment machine. No real cloud jobs or texts were created during local verification.
7. **Verify production context parity.** Docker copies only `data/eboardMembers.json`.
   Planning history/taxonomy and local skill/history fallbacks are not shipped. Deepagents
   simple drafts explicitly fall back to idea-only planning without history; default mock
   planning cannot do that. Provision reviewed context privately or store it in shared storage;
   do not bake the entire private data directory into the image.
8. **Strengthen release checks.** Main deploy workflow does not depend on migration tests
   (they run in a separate workflow), frontend typecheck, or frontend UI tests. Add explicit
   gates. Investigate `requestUi.test.mjs`: all nine assertions pass but its process stays
   alive in this environment, preventing the full Node suite from completing.
9. **Update documentation and complete live acceptance.** Reconcile stale architecture and
   connection claims. Verify fresh invite → password → correct profile/admin rights, browser
   and Photon reassignment through all three actors, denial, duplicate delivery, expiration,
   unknown sender, changed ownership and a stopped laptop. Verify exact hosted migration
   history and worker configuration without blindly replaying existing migrations.

## Verification evidence

- Backend: 478 tests passed, including invitation fix; Ruff passed.
- Database: all 42 migration/RPC tests passed against local PGlite, not hosted Postgres.
- Frontend: 20 Vitest UI tests, TypeScript check and production build passed.
- Frontend Node suite: nine request UI assertions pass but process does not exit. Session
  refresh's seven tests and the remaining targeted reassignment/profile/speech/task-mapping
  group (21 tests) pass separately. Do not call the complete Node suite green.
- Messaging: 12 bridge tests and typecheck passed; Photon send helper's two mock tests passed.
- No real member texts, invitations, hosted data writes or deployments were performed for
  this audit. Passing mocked tests does not establish live provider delivery.

Recommended sequence: task authorization → shared proposals and activation → recording
correctness/storage → scheduled notifications → production context and release gates →
live multi-user acceptance. Existing authentication, roster and Sheets work can be retained.

Follow-up: reassignment is now admin-first, then recipient consent, with name/number choices and immutable completed-handoff history. See HELP_WORKFLOW.md.
