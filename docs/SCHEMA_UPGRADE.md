# One UUID task store

Meeting extraction, tracker imports, messaging, and the dashboard now use
`public.tasks` with UUID IDs and `todo`, `in_progress`, `blocked`, or `done` status.
The old timeline accepts `open` as an input alias for `todo`; responses use the
canonical statuses. Numeric task URLs must be replaced with UUID URLs.

The dashboard reads/updates `/api/tasks/records`, with pagination. `/api/tasks`
and `/api/tasks/{uuid}/status` retain the timeline view over those same rows.
Meeting-generated tasks preserve precise deadlines and the original spoken text.
`due_date` remains canonical: changing or clearing it takes precedence over a
previously extracted timestamp. Extracted names are stored in `assignee_text`;
they do not create members or grant access to personal messaging tasks.

## Existing UUID database (the current hosted schema)

Back up the database, then review and apply
[`20261115010000_unify_meeting_tasks.sql`](../supabase/migrations/20261115010000_unify_meeting_tasks.sql)
in the Supabase SQL editor. This migration is transactional and can be reapplied.
It creates the missing meetings and UUID dependency tables and adds meeting
provenance columns. Existing UUID task IDs, task codes, ownership and timestamps
are unchanged. No credentials are included in the migration.

Deploy the updated backend/frontend together with that schema change. Verify a
synthetic meeting upload, refresh the task list, and update its status. Real Gemini
and hosted database writes are separate from the offline regression tests.

## Fresh installs

Apply all files in `supabase/migrations` in filename order using the Supabase CLI.
Supabase supplies `auth.users`, `auth.uid()`, and its managed database roles.
The historical `0001_init.sql` bootstrap now skips an existing task store; the
following canonical-task migration preserves numeric tasks before creating UUID
tasks. The profile migration has the unique version `20261114120001`, fixing its
collision with `20261114120000_add_messaging_members.sql`.

For databases with existing CLI migration history, inspect `supabase migration
list` before using `db push`. A database that applied profiles under the old shared
version needs its history reconciled with the actual installed tables. Do not
reapply the profile table migration or blindly repair migration history. Applying
the new schema upgrade directly does not require replaying historical migrations.

## Existing numeric database

Back up the database and apply the remaining ordered migrations, starting with
`20261114080000_create_tasks.sql`. That migration moves the old task and dependency
tables into the private `winnie_legacy` schema. It does not delete them. Meetings,
people, and seats remain available for the conversion.

The new upgrade copies the old tasks into UUID records, maps `open` to `todo`,
preserves assignment text, deadlines, review flags, meeting links and dependency
edges, and records the numeric ID in `legacy_task_id`. Use that column to resolve
old bookmarks; original rows and timestamps remain in `winnie_legacy.tasks`.
No public-to-member grants are added. If old data violates canonical constraints,
the copy fails and rolls back rather than silently truncating data.

Do not remove the archive until the migrated data and dependent clients have been
verified. Reapplying the upgrade does not duplicate migrated tasks or edges.

## Admin reassignment approvals fail with `task_reassignment_review_state`

An installation retaining the recipient-first review constraint rejects the
admin-first intermediate state: `admin_decision = 'approved'`, `status = 'pending'`,
with reviewer metadata populated. Run
[`20261115230000_repair_reassignment_review_state.sql`](../supabase/migrations/20261115230000_repair_reassignment_review_state.sql)
in the project's SQL editor, or through an authenticated database connection.
It transactionally restores the matching admin-review and recipient-response RPCs,
guard trigger, review constraint and notification functions. This also repairs a
partially upgraded installation whose old guard never sets `reviewed_at` when admin
approval leaves the request pending. It can be reapplied safely and does not rely
on the original migration's one-time function renames.

Existing task ownership and completed decisions are preserved. Any legacy acceptance
before admin review is archived and requires fresh recipient consent after approval.
Unsent messages advertising the obsolete workflow are cancelled; the repair creates
no messages and does not approve or transfer any pending task. Authorization still
requires the existing verified administrator and recipient identities.

After applying it, retry approval from an authorized administrator account. The
request should await recipient consent and retain its current owner until the
recipient accepts. A rejection or recipient denial must not transfer ownership.

## Verification

`supabase/tests/schema-chain.test.mjs` executes the complete ordered migration
chain in PostgreSQL/PGlite, checks conversion with existing numeric tasks and
dependencies, and verifies that existing UUID records are untouched. Python tests
exercise ingestion, retry deduplication, timeline reads, deadline edits and UUID
status updates. Frontend tests check the actual record URLs and UUID handling.
