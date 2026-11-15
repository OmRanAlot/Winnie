# Original assignments and reassignment requests

The active workflow is now administrator approval first, recipient consent second. Apply 20261115195000_admin_first_reassignment.sql and follow [HELP_WORKFLOW.md](HELP_WORKFLOW.md); older instructions below describe historical migrations.

Apply `supabase/migrations/20261114160001_task_original_assignee_and_requests.sql`
to the existing UUID task store, after the roster/profile migrations. Apply this file
alone; the older `0001_init.sql` defines a different, incompatible tasks table.

`tasks.original_assignee_code` references `members.code`. It captures the first
individual assignee and survives later changes to `owner_code` and `assignee_text`.
Existing tasks are backfilled from the current owner or an exact alias for the task's
semester. Multi-person or unknown assignments remain NULL. This baseline cannot
reconstruct changes made before the migration. An entirely unassigned task captures
its original assignee when first assigned. Historical ambiguous assignments stay NULL.

`task_reassignment_requests` stores the task, requesting member, proposed member,
reason, status, original assignment snapshot, timestamps, and reviewing profile.
`pending_task_requests` is a view of requests whose status is `pending`.
Resolved requests stay in the underlying table for history.

Signed-in active members submit requests through the RPC below. Their identity comes
from their linked profile, not a browser-supplied member code. Only an active President
or Vice President in the roster, or a profile with `is_admin = true`, can review them.
Requesters can read their own requests; reviewers can read all requests. Anonymous
clients cannot access the queue, and authenticated clients cannot write the table
directly. Trusted server credentials retain access, as with the existing task store.

```javascript
// Use the Supabase client with the member's authenticated session.
const { data, error } = await supabase.rpc('submit_task_reassignment', {
  p_task_id: taskId,
  p_proposed_assignee_code: proposedMemberCode,
  p_reason: 'I have a scheduling conflict.',
});

const pending = await supabase.from('pending_task_requests')
  .select('*').order('created_at');

// In the president / VP / admin's authenticated session:
const decision = await supabase.rpc('review_task_reassignment', {
  p_request_id: requestId,
  p_decision: 'approved', // or 'rejected'
  p_review_note: 'Approved after reviewing availability.',
});
```

Approval changes `tasks.owner_code` and `tasks.assignee_text` atomically with the
request status. Rejection leaves the task unchanged. An approval fails if the task
was completed, its assignment changed since submission, or the proposed assignee is
no longer active. Original assignment history remains intact. Only one pending
request per task/requester is allowed. Repeated decisions cannot apply twice.

The frontend signs in with Supabase Auth and loads the user's profile plus
`can_review_task_requests()`. It uses these RPCs for Send/Approve/Deny, and the
Requests screen reads the persisted queue and decision history. After each successful
mutation it reloads tasks, member assignments, and requests. Other sessions refresh
every 15 seconds and on window focus, with a manual Refresh button. Fetch errors are
shown explicitly; sample tasks and sample requests are never substituted.

The task details show the original assignee and let a linked member choose a proposed
replacement without requiring AI suggestions. Member identity is always the signed-in
profile, even when a reviewer views another member's dashboard. Database RLS limits
ordinary members to their own requests. These operations do not send external messages.

An active President/VP roster entry must be linked to a login profile to approve
requests. Alternatively, a trusted administrator can explicitly grant `profiles.is_admin`
to a known account. No privileges are inferred from a typed username or granted by
the frontend. At the live access audit, the President and VP were present in the roster
but had no linked profiles, and no existing profile had `is_admin` enabled.

Validation: `node --test supabase/tests/reassignment.test.mjs` runs the migrations
in PostgreSQL via PGlite with synthetic members, profiles, and tasks.
