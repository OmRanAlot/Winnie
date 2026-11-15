# Shared Photon and browser reassignment workflow

The active workflow now uses `task_reassignment_requests` for both channels. Apply
`20261115150000_reassignment_recipient_consent.sql` and then
`20261115160000_unify_photon_reassignments.sql` once, after the earlier migrations.
Deploy the updated backend and frontend, then restart the Photon listener. The older
HELP approval commands and RPC ownership-changing path are disabled. HELP records
retain the saved Gemini recommendations and link the selected proposal to a shared
REQ record. Eligible existing pending HELP proposals are linked during migration;
ones with unverifiable accounts or ownership require administrator review.

The flow is:

1. The owner texts `help WIN-...`, or asks Gemini for a replacement for one specific task.
2. Gemini suggests eligible members using the saved role/skills and current workload.
3. The owner selects `choose HELP-... MEMBER_CODE`. This saves a **REQ-number** in the same
   queue as frontend requests. Alternatively, `reassign WIN-... to MEMBER_CODE` requests
   a specific member directly.
4. The recipient opens **Requests** and accepts/denies, or texts `accept REQ-...` / `deny REQ-...`.
5. After acceptance, an admin reviews **Requests**, or texts `approve REQ-...` / `reject REQ-...`.
6. Ownership transfers only after both acceptance and approval. Denial keeps the owner.

Text `requests` to see pending requests and their REQ numbers. Bare yes/no does not
accept a transfer. The Gemini interpreter can identify a request for help; it never
selects or approves a replacement. Ambiguous task references prompt clarification.

Text actions use the same verified profile and admin/role checks as browser RPCs.
A separate `members.messaging_admin` flag is no longer used for REQ decisions. Members
need an active, consenting, verified messaging identity and a linked Auth profile with
completed password setup. Shared/ambiguous imported assignments require review before
text transfer; the adapter never silently removes other co-owners.

The existing notification worker polls the new durable outbox before historical help
notifications. Requests, accepted proposals, and final decisions queue only one notice
per event/member. Delivery requires an active consenting member and a verified iMessage
identity with `reminders_enabled=true`. Uncertain sends are recorded, not blindly retried.
New reassignments use DMs and the shared queue; they do not create Photon group chats.
No message is sent by applying SQL alone; sends occur when the configured listener polls.

For the deployed demo, set these Cloud Run environment variables:

```dotenv
WINNIE_MESSAGE_AI_ENABLED=true
WINNIE_HELP_WORKFLOW_ENABLED=true
WINNIE_HELP_GROUPS_ENABLED=false
```

Keep the Gemini API key and matching bridge secret in backend secrets. On the machine
running Photon, `messaging/.env` must contain:

```dotenv
BACKEND_URL=https://hack-princeton-514716.web.app
HELP_POLL_ENABLED=true
```

Keep its existing `PROJECT_ID`, `PROJECT_SECRET` and `MESSAGING_BRIDGE_SECRET` private.
Restart with `npm start` from `messaging/`. Deploying FastAPI does not run this separate
Spectrum listener automatically.
The listener allows up to 60 seconds for a backend reply because natural-language
help can require both Gemini interpretation and candidate matching.

Test with a disposable task: text a help request, choose a candidate, find the REQ in
both accounts, verify admin approval is blocked before acceptance, accept from the
recipient, approve as admin, and reload the task in both accounts. Repeat with denial,
an unrelated sender, a duplicate message ID, and a task edited before approval. Check
that failed/stale requests do not transfer ownership. Automated tests use synthetic
identities and exercise these guards without sending actual Photon messages.

For laptop-independent operation, use [signed Photon webhooks](PHOTON_WEBHOOK.md)
on the existing backend. In that mode Cloud Tasks replaces the development listener's
notification poll; no additional always-running server is required. The listener
instructions above remain useful only for development/stream mode.
