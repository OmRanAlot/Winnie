# Winnie — implementation context

## Purpose and source of truth

Winnie is an iMessage-first AI agent for the NJIT Women in Computing Society (WiCS), built for HackPrinceton. It keeps the executive board aligned by turning meeting context into actionable plans and maintaining task progress through short text conversations.

This document translates the supplied project description into an implementation contract. `docs/GAMEPLAN.md` defines build order; `docs/API.md` defines proposed endpoints. These documents describe the target behavior, not completed functionality. The initial repository implements only the API health endpoint and frontend shell.

## Who we serve

WiCS runs about seven events each semester, including GirlHacks, the WiCS Gala, industry events, collaborations, and technical workshops. Its 12 board positions are President, Vice President, Treasurer, Secretary, two Event Coordinators, two Industry Partnership Chairs, Community Outreach Chair, two PR Chairs, and Technical Director.

Today, tasks are scattered across spreadsheets, Google Docs, Discord, meetings, and email. Progress goes unreported, dependencies stall, workload is uneven, and the President spends hours constructing event plans. Winnie should reduce the effort required to keep this information current. Members primarily interact through iMessage; the dashboard supports shared visibility and review.

## Hackathon scope

Ship one coherent flow before expanding integrations:

1. Show 12 fictional member profiles with roles, skills, capacity, and current tasks.
2. Ingest a pasted meeting transcript with explicit consent metadata.
3. Accept an event name, date, and short planning prompt.
4. Produce a structured draft with tasks, proposed owners, deadlines, dependencies, explanations, and evidence from the transcript.
5. Let the President edit, approve, or reject the draft on the dashboard.
6. Activate only the approved tasks and send each owner their relevant assignments.
7. Accept `done <task-id>` and `need help <task-id>` through messaging; accept bare `done` only with one unambiguous pending task in that conversation.
8. Run deadline/overdue reminders, stopping when tasks are completed or events canceled.
9. Reflect text updates in the dashboard and notify only relevant stakeholders.

Minimum dashboard: board roster, event form, transcript input, proposal review, approved task list, and status/error feedback. A simple date-ordered task list comes before a full Gantt component.

Stretch scope: live audio recording/transcription, shared-inbox triage and response tracking, spreadsheet/Docs sync, full Gantt chart, automatic workload monitoring, reassignment suggestions, two-week event confirmation, historical template retrieval, and AI execution of suitable tasks. Reassignment proposals can be demonstrated early, but must retain approval and recipient acceptance.

## Demo story

Use a fictional spring workshop with an explicitly selected future date. A transcript mentions room booking, a materials list, and buying materials. The President requests a plan. Winnie assigns the materials list to an Event Coordinator and the purchase to the Treasurer, with a dependency between them. The President edits a deadline and approves. The Coordinator receives a text, replies `done <id>`, and the Treasurer sees their purchase task become ready. A separate overdue task demonstrates a reminder and `need help` without silently reassigning anyone.

Use synthetic names and opted-in demo phone numbers. Support mock messaging with a visible outbox if provider setup fails; distinguish simulated delivery from actual iMessage delivery in the demo.

## Architecture

```text
React dashboard ──HTTP──> FastAPI routes ──> business services ──> repository
                              │                    │                 │
                              │                    │            Cosmos DB
                              │                    └──> notification outbox
                              │                                  │
                              └──> agent planner           worker ──> Photon ──> member
                                      │                                  │
                               structured proposal        inbound adapter <── reply
                                      │                         │
                              President approval          task update service
```

React + TypeScript + Vite is the dashboard. FastAPI owns authorization, validation, domain transitions, integrations, and audit records. Python services enforce rules shared by the dashboard, agent tools, inbound messages, and scheduler. The browser never connects directly to Cosmos, Photon, or a model provider.

Cosmos DB for NoSQL is the target canonical application store. Start with a repository interface and an in-memory implementation for development; memory mode is explicitly temporary and resets on process restart. Do not let agent conversation memory become the source of truth for task status.

Use a separate worker process for scheduled scans and outbox delivery. Do not start jobs in the API module, where development reload or multiple workers could repeat them. The MVP can poll API data from the dashboard; WebSockets are optional.

## Agent design

Use LangChain Deep Agents for the event planning workflow, behind an adapter. Its top-level planner gathers context, drafts tasks, proposes assignments, checks dependencies/timing, and requests review. A mock planner should return schema-valid fixture output for offline development.

Logical specialist responsibilities from the original description:

| Specialist | Input | Output |
| --- | --- | --- |
| Transcript analyst | Transcript and event context | Action items, decisions, open questions, evidence |
| Assignment/workload | Draft tasks and member load/skills | Proposed owners, rationale, conflicts |
| Timeline | Event date and dependent tasks | Proposed deadlines, ordering, impossible schedules |
| Email triage, stretch | Minimal relevant inbox metadata/content | Responsible role, response deadline |
| Notification, stretch | Validated updates and subscribers | Suggested recipients and concise copy |

Begin with extraction, assignment, and timeline as explicit steps with validated outputs. They can become specialized subagents without changing the application contract. Keep domain updates deterministic; the model proposes rather than directly assigning or sending.

Use structured schemas, stable IDs, transcript evidence, and explicit unknowns. Never invent a person's commitment, a sponsor agreement, or a deadline from missing context. Flag uncertainty in the proposal. Reject nonexistent owners, dependency cycles, cross-event references, and impossible date orderings before presenting an approvable plan.

Deep Agents planning state, virtual files, durable cross-run memory, and application records are separate concerns. Human-in-the-loop pause/resume needs a checkpointer and a stable thread identity. Cosmos application storage does not automatically provide a Deep Agents checkpointer or file backend. Choose and test a compatible durable implementation (or a deliberate custom adapter) before claiming restart-safe agent resumption. Until then, save structured proposals and approvals in the application repository and explicitly label agent execution as non-durable.

Store transcripts and historical plans outside the prompt and retrieve relevant material on demand. The virtual filesystem is an agent context mechanism, not permission to read arbitrary host files. Treat transcripts, inbound text, and email as untrusted content; their instructions cannot override tool permissions or approval rules.

## Domain model

Use UUIDs internally and a distinct short task reference for texts. Store timestamps in UTC and render/schedule using `America/New_York` by default. Parse date-only inputs in the event's timezone, with a displayed explicit default deadline time (proposed: 5 PM local); never use ambiguous server-local time.

All persisted records carry `id`, `board_id`, `type`, `created_at`, `updated_at`, and a version/ETag for concurrency control.

| Record | Key fields |
| --- | --- |
| Member | name, position, skills, capacity, verified messaging identity, notification consent/preferences, active |
| Event | name, description, event date/time, timezone, status, president/approver ID |
| Transcript | event ID, text/reference, uploader, consent confirmation/time, participant scope, retention date |
| PlanProposal | event ID, revision, source transcript IDs, proposed tasks, warnings, agent run ID, status |
| Task | event ID, short reference, title, description, owner ID, due time, estimated effort, status, dependency IDs, interested member IDs, proposal/source evidence |
| Approval | proposal ID + revision, actor, decision, timestamp, approved payload/version |
| Conversation | verified member ID, provider conversation ID, pending task references, last inbound provider event ID |
| Notification | recipient, task/event ID, type, trigger/version, dedupe key, due time, delivery state, attempts, provider message ID |
| AuditEntry | actor/source, action, target ID, before/after summary, correlation ID |
| Email, stretch | provider thread/message IDs, assigned owner, category, response deadline/state; minimize stored body |

Suggested initial Cosmos layout: one `board-data` container partitioned on `/board_id` with record `type` discriminators. This keeps the single-board demo simple and allows same-partition transactional batches. Measure queries before generalizing; large transcript bodies can later move to private object storage. Validate dependency references at the service layer; Cosmos is not a relational foreign-key engine.

## State transitions and approval

- Event: `draft → active → completed`, or `canceled`.
- Proposal: `draft → pending_approval → approved | rejected | superseded`.
- Task: `todo → in_progress → done`; use `blocked` when the owner needs help or an unmet dependency prevents work. A completed task can be reopened explicitly with an audit entry.
- Notification: `queued → sending → sent | failed`, with retry metadata. Provider acceptance is not proof of recipient delivery; record receipts separately if supported.

Draft proposal tasks do not become live assignments. Approval must check the President's identity, exact proposal revision, and current state; atomically create approved tasks, an audit record, and queued assignment notifications. Repeated approval must return the existing outcome without duplicating tasks or texts. Editing a pending proposal creates a new revision; stale approvals fail with a conflict.

Consequential actions require review: activating an event plan, reassigning a task, and messages to external contacts. Reassignment requires President approval and the new owner's acceptance before changing the canonical owner. Ordinary internal reminders and task completion acknowledgements can run automatically after opt-in. Revalidate permission/state immediately before any side effect; an LLM tool interruption alone is not authorization.

For local mock-only development, a clearly labeled server-configured demo actor can stand in for authentication. Before exposing writes or enabling real messages, implement verified dashboard identity and server-side President/member authorization. A role selected in the browser is not authentication. Members may update their own tasks; President/VP visibility does not imply identical approval permissions.

## Messaging behavior

The supplied brief calls the Photon integration `textMessage`. Treat that as a product requirement, not a confirmed SDK method. Photon has multiple API/package boundaries; confirm the actual account entitlement, transport (webhook versus stream), sender setup, authentication, payload fields, inbound authenticity mechanism, and send contract during the first technical spike. A small Node bridge may be needed if the selected contract is JavaScript-only; don't mix it into the browser bundle.

Normalize provider payloads into an internal inbound-message schema at the adapter boundary. Verify the provider's documented signature/authentication before parsing; ignore self-sent messages, deduplicate provider event IDs, map the sender to a verified member, and reject unsupported/unknown identities. For streaming providers, use a trusted internal bridge instead of pretending the provider supplies webhooks.

Example: `Winnie: Create the workshop materials list by Apr 9, 5 PM ET. Reply DONE W-104 or NEED HELP W-104.` A bare `done` with several candidate tasks triggers a disambiguation reply and no mutation. Explicit references still require ownership checks. `Need help` marks the task blocked and opens a reviewable help/reassignment request. Acknowledge corrections such as `not mine`; preserve the current owner until an approved handoff completes.

Notify recipients from explicit dependencies, subscriptions, and leadership visibility rules, excluding unrelated board members. Completion of a materials list should notify the owner of the dependent purchase task. Do not ask the LLM to invent recipients from the whole contact list. Honor opt-out and quiet hours; keep private transcript snippets out of routine texts.

## Scheduling and delivery reliability

For incomplete tasks, calculate reminders seven calendar days before, three calendar days before, and the previous calendar evening at 6 PM in the task/event timezone. Only schedule a trigger if it is before the deadline and was not already passed when the task was created. Use timezone-aware calendar arithmetic for daylight saving changes. Overdue nudges start after the due time, with a proposed maximum of one per day; tune from feedback.

On each scan, find newly due triggers since the previous scan, recheck task/event/consent state, and enqueue with a unique key such as `(task_id, deadline_revision, reminder_kind, recipient_id)`. Persist sent/queued keys to prevent repeated scans from duplicating messages. Completion or cancellation invalidates pending reminders. A changed deadline invalidates unsent notifications for the old revision and calculates new future triggers.

Keep an outbox so domain updates and notification intent are committed together. Retry temporary failures with backoff and bounded attempts; surface permanent failures on the dashboard. Recheck task status and notification validity before sending. Handle the crash-after-send case using provider idempotency if available; otherwise disclose the remaining duplicate-delivery risk and reconcile provider message IDs. A separate worker needs a claim/lease before scaling beyond one instance.

Stretch scheduling: once per event, 14 calendar days before the event, ask the President whether it is still going ahead. Email response reminders need provider thread-response evidence; an outbound message to an unrelated thread must not clear them.

## Privacy and corrections

Require consent confirmation and access restrictions before storing real meeting material; text upload also needs the uploader's confirmation that sharing is authorized. Audio recording/transcription is deferred. Decide retention and deletion behavior before real recordings. Keep the demo synthetic. Restrict transcript visibility to authorized board members, redact secrets/phone numbers from logs, and scope any future inbox access to the necessary shared mailbox. Log corrections, approvals, status changes, and notification outcomes without copying full private message bodies into routine logs.

## Integration decisions to close early

1. Which exact Photon API/account can we use, and can we receive and reply to a real opted-in phone today?
2. Which LLM provider/model is funded and supports the structured output/tool workflow we need?
3. Is Cosmos available, and will the demo use a server key or managed identity?
4. Which auth mechanism identifies the President and each member for real writes?
5. Where will API, worker, frontend, and any messaging bridge run? A webhook requires a public HTTPS endpoint; localhost alone will not work.
6. Which durable checkpointer/backend supports the selected Deep Agents release? If not ready, demonstrate persisted proposals without claiming durable agent memory.

Do not block local UI or domain work on these answers. Use explicit mock adapters and replace one boundary at a time. Add and lock provider dependencies after the smallest integration works. The starter's dependency ranges need a tested Python lock before collaborative deployment; commit the generated npm lockfile.

## Reference documentation

Reviewed November 14, 2026. Verify exact versions/contracts during integration:

- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop): tool review and checkpoint-based pause/resume.
- [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends): virtual files and storage backend choices.
- [Photon integration guidance](https://github.com/photon-hq/skills/blob/main/skills/imessage/SKILL.md): select a single API/package boundary before using its methods.
- [Photon](https://photon.codes/): confirm current integration documentation through the chosen account/product.
