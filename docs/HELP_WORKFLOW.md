# Shared Photon and browser reassignment workflow

The current order is **owner request → administrator approval → recipient consent → transfer**.
Apply `20261115195000_admin_first_reassignment.sql` after the existing migrations, then
redeploy backend and frontend. Earlier recipient-first instructions are superseded.

1. Text a task-specific request such as “I need a replacement for room booking,” or
   `help WIN-202611-1`. Gemini proposes candidates using roles, skills and current workload.
2. Suggestions are numbered and show names. Reply `Taylor Example`, an unambiguous first
   name, or `1`. Explicit `choose HELP-5 Taylor Example` also works without chat context.
   Member codes remain accepted for compatibility but are never required by the prompt.
   Ambiguous names do not create a request; use a full name or saved list number.
3. Alternatively, text `reassign WIN-202611-1 to Taylor Example` for a specific active member.
   Numbers in direct transfer commands are not resolved against an undisplayed roster.
4. The shared REQ enters admin review. Only administrators/reviewers are notified at this stage.
   They use Requests or simply text `approve` / `reject` when one request is clear.
   With multiple requests, Winnie asks which task and accepts a task name or list number.
   Natural instructions such as “please reject the room booking transfer” use Gemini to
   select a verified pending request, then the backend independently checks authorization.
   Explicit `approve REQ-5` / `reject REQ-5` commands remain supported.
5. Approval records the administrator and time but leaves the original ownership unchanged.
   It then queues a consent message for the recipient, who uses Requests or `accept REQ-5`
   / `deny REQ-5`. The recipient cannot accept before admin authorization.
6. Acceptance transfers ownership atomically and records `handoff_completed_at`, the outgoing
   owner/assignee snapshot, requester, administrator and recipient response. The original
   assignee remains unchanged. Only completed transfers count in transfer metrics.
   Administrator rejection or recipient denial preserves ownership.

Text `requests` to inspect the current stage. A bare yes/no never approves a transfer.
Natural request decisions require `20261115210000_conversational_request_context.sql`
after the earlier reassignment migrations and an updated backend deployment. No frontend
change is required for this addition. The public Photon readiness endpoint reports
`request_action_protocol: 1` on the updated backend. Gemini-based named decisions require
`WINNIE_MESSAGE_AI_ENABLED=true`; straightforward unambiguous commands also work without
a model call. Current role and stage always come from verified live database context,
not a person's claim to be an admin or old conversation history.
The model proposes; deterministic RPCs verify identities, stages, active roster/consent,
password setup, current ownership and completion state. It cannot transfer tasks directly.
An obsolete/completed task cannot be accepted. The recipient may deny an obsolete request
so a fresh one can be created. Admin approval is not a completed transfer.

Historical completed decisions remain intact. On upgrade, open pre-admin recipient responses
are retained in `legacy_recipient_response`, and fresh consent is requested after admin review.
Unsent open-request messages advertising the old order are cancelled and admin review notices
are queued. The migration itself sends nothing.

Browser and Photon use the same `task_reassignment_requests` record. Phone identities must be
verified and linked to active, consenting profiles with completed password setup. The app's
`is_admin` flag or approved President/VP role determines review rights; the separate old
`messaging_admin` flag does not authorize REQ decisions. Multi-owner text handoffs still fail
closed when the outgoing owner cannot be represented safely; no other co-owner is discarded.

Use [PHOTON_WEBHOOK.md](PHOTON_WEBHOOK.md) for cloud inbound/reply delivery and
[AUTOMATION.md](AUTOMATION.md) for scheduled recovery of pending notices. Keep the local
stream listener stopped in webhook mode. Configure `WINNIE_MESSAGE_AI_ENABLED=true` and
`WINNIE_HELP_WORKFLOW_ENABLED=true`; keep provider and bridge credentials server-side.
New transfers use direct messages and do not create group chats.

Test: request by name → admin gets review notice → approval leaves owner unchanged →
recipient gets consent notice → acceptance changes owner and preserves original owner/history.
Repeat with rejection, denial, wrong actor, revoked access, changed ownership, duplicate provider
IDs and a stopped laptop. Automated tests use synthetic identities and send no real messages.
