# HackPrinceton execution plan

## Build strategy

Optimize for a convincing end-to-end story: paste a transcript, draft a workshop plan, approve it, receive an assignment, reply by text, and see the task change. The scaffolding is in place; this plan describes remaining implementation. Estimates below are flexible working blocks rather than promises about the event schedule or team size.

## Phase 0 — prove the risky integration (first 60–90 minutes)

- Run the React/FastAPI scaffold using `README.md` and confirm the dashboard health indicator.
- Confirm Photon access and the exact API boundary. Send a message to an opted-in test member and receive one reply. Record the real payload, identity/authentication rules, and whether a bridge is required.
- Make one schema-constrained model call using the team's chosen provider.
- Create/connect a Cosmos test container and write/read one fictional record.
- Choose the dashboard identity mechanism and deployment target; reserve a stable public HTTPS callback URL if required.

Exit: the team knows which providers work and has explicit mock fallbacks for those that don't. Time-box Photon investigation, but keep its proof early because iMessage is the central differentiator. Record unresolved assumptions in `CONTEXT.md`.

## Phase 1 — domain and fixtures (about 2 hours)

- Define shared API schemas before splitting implementation work.
- Add fictional fixtures for 12 board members, one workshop, one transcript, a dependent task pair, and one overdue task. Do not invent real people's identities.
- Implement repository interfaces, a memory adapter, and seed/reset tooling that cannot accidentally wipe a live database.
- Implement members/events/tasks listing and member workload derived from unfinished tasks and effort.
- Build board roster, event detail, task cards, empty/loading/error states, and task status editing.

Exit: the UI reads actual API fixtures; refreshes fetch canonical task state. No API route pretends a provider operation succeeded.

## Phase 2 — proposal and approval, without an LLM (about 2–3 hours)

- Add consent-aware transcript ingestion and event planning form.
- Implement a deterministic mock planner returning the agreed proposal schema.
- Build proposal editing, evidence display, uncertainty warnings, and President review.
- Validate owners, dates, dependencies, cycles, and proposal revisions.
- Add approval/rejection endpoints with authorization and idempotent activation.
- Persist tasks, audit entries, and assignment notification intents on approval.

Exit: a draft never creates a live assignment, stale approval fails safely, and pressing approve twice never doubles the work. Keep the mock provider label visible.

## Phase 3 — real agent planning (about 2–3 hours)

- Install and lock selected Deep Agents/model dependencies after the spike works.
- Implement transcript extraction with evidence and structured output validation.
- Add assignment by skills/capacity and timeline ordering; deterministic validation owns constraints.
- Expose progress (gathering context, extracting, assigning, timeline, ready for review) with a run ID.
- Add bounded retries/timeouts, visible failure recovery, and no silent replacement of failed real output with a mock plan.
- Persist structured proposals; only claim durable pause/resume after testing a durable checkpointer through a process restart.

Exit: real model output produces an editable, valid proposal from the workshop transcript, with missing information flagged instead of invented.

## Phase 4 — messaging and reminders (about 3 hours)

- Implement a mock outbox and the verified Photon adapter behind the same interface.
- Queue approved assignments, then deliver them through the worker.
- Authenticate/deduplicate inbound events and map verified senders to members.
- Implement `done <id>`, `need help <id>`, ownership checks, and ambiguity handling.
- Propagate completion to the dashboard and notify only relevant dependent owners/subscribers.
- Implement reminder calculation with an injectable clock and persistent dedupe records.
- Cancel obsolete reminders on completion, cancellation, or changed deadlines; show delivery failures.

Exit: one real phone reply updates one correct task, webhook retries do not duplicate the update, and scanning twice does not send the same reminder twice. Use a labeled demo clock for fast reminder demonstration rather than changing a production clock.

## Phase 5 — persistence and demo hardening (about 2 hours)

- Replace memory persistence with Cosmos using the same repository contract; verify read/write and concurrency behavior.
- Ensure approval + task creation + notification intent are atomic within the selected partition design.
- Finish server-side authorization before enabling real data or externally reachable write endpoints.
- Connect deployment secrets, API origin/CORS, public callback, worker configuration, and any bridge.
- Pin dependencies, document the tested runtime, and verify setup on a teammate's machine.
- Exercise the full story, including timeout, rejected proposal, unknown sender, and failed message delivery.
- Prepare a synthetic seed dataset, a labeled mock fallback, and a short screen recording.

Exit: restart the backend and show that approved tasks and delivery dedupe records survive. Record any agent-checkpoint limitation separately.

## Optional parallel work lanes

If multiple teammates are available after agreeing the schemas, divide work by boundary:

| Lane | Owns | Coordination point |
| --- | --- | --- |
| Dashboard | roster, events, transcript form, plan review, task status | Uses `docs/API.md`; starts against mock responses |
| Domain/API | schemas, repositories, approvals, authorization, audit | Publishes contract changes before UI/agent changes |
| Agent | extraction, assignment, timeline, structured proposals | Returns proposals; never bypasses approval services |
| Integrations | Photon spike, inbound adapter, worker, Cosmos setup | Uses normalized schemas and service interfaces |

With fewer teammates, combine domain + integration and dashboard + agent work. Keep fixture IDs, schema names, status values, and timezone defaults consistent. Integrate after each phase rather than waiting until the final hours.

## Planned file ownership

```text
backend/app/routes/          members.py, events.py, transcripts.py, plans.py, tasks.py, webhooks.py
backend/app/models.py        domain dataclasses (split into a package only if it outgrows one file)
backend/app/schemas.py       request/response shapes (same rule)
backend/app/services/        plans.py, tasks.py, replies.py, notifications.py
backend/app/agents/          planner.py, transcript.py, assignment.py, timeline.py, schemas.py
backend/app/integrations/    repository.py, memory.py, cosmos.py, messaging.py, photon.py
backend/app/jobs.py          reminders and delivery worker (becomes a jobs/ package with worker.py, reminders.py, delivery.py if it grows)
frontend/src/features/      members/, events/, tasks/, transcripts/, approvals/
frontend/src/components/    common UI
frontend/src/lib/           API client and typed contracts
```

These are intended modules, not empty implementations to fill indiscriminately. Create them as each feature lands.

## Meaningful verification

- Approval: unauthorized actor denied; stale revision rejected; duplicate approval creates one task set and one assignment per recipient.
- Agent: evidence-backed extraction; unknown owner flagged; malformed output rejected; dependency cycle and impossible deadline rejected.
- Text replies: explicit ID completes the right owned task; ambiguous `done` asks for clarification; unknown sender cannot update; duplicate provider event produces one transition.
- Reminders: seven-day, three-day, and previous-evening triggers; short-notice creation skips past triggers; daylight saving transition; repeated scan, completed task, canceled event, and edited deadline.
- Persistence/delivery: restart retains tasks and dedupe state; a failed send retries within bounds and appears as failed if exhausted.
- UI: loading, errors, empty events, readable mobile layout, review/approval, and status refresh after a message.

Test real domain behavior as it is implemented; do not build a large test framework for the static dashboard shell.

## Feature cuts if time runs short

Cut live audio first, then email, spreadsheet/Docs sync, rich Gantt visualization, historical retrieval, and autonomous reassignment. Retain plan review, the text completion loop, and a basic reminder. Use an honest mock outbox if Photon remains unavailable. Do not sacrifice approval enforcement to make the demo appear more autonomous.

## Final demo checklist

- [ ] Credentials are out of git and browser assets; all demo participants opted in.
- [ ] Fresh setup works using `README.md`; provider mode is visible.
- [ ] 12 fictional member profiles and a future workshop are seeded.
- [ ] Transcript creates a draft with owners, dates, dependencies, and evidence.
- [ ] President can edit and approve; assignments appear only after approval.
- [ ] One actual iMessage completion updates the dashboard, or the fallback is labeled simulated.
- [ ] Completion notifies the dependent owner without messaging the whole board.
- [ ] Reminder demo stops after completion and cannot double-send on a repeated scan.
- [ ] `Need help` surfaces a blocked task without silently replacing its owner.
- [ ] Known limitations and next steps are stated accurately.
