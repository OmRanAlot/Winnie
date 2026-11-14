# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The stack is chosen and the file structure is scaffolded, but every source file is still comment-only (no logic yet). Dependencies are installed. When integrations are actually built, replace the "Planned integrations" section with what was built.

## Stack and layout

| Path | What | Stack |
|---|---|---|
| `backend/` | API, data, and all agent/business logic | Python 3.13, uv, FastAPI, SQLAlchemy, APScheduler |
| `messaging/` | Sidecar that only relays DMs between Photon and the backend | Node, TypeScript, `@photon-ai/advanced-imessage` |
| `frontend/` | **Placeholder.** The UX team's design will replace this folder entirely, so don't invest in it. | Vite, React, TypeScript |

Photon ships only TypeScript SDKs (no Python), which is why `messaging/` exists. Keep business logic out of it: it forwards inbound DMs to `POST /webhooks/messaging` and exposes `POST /send` for the backend.

Backend layering: `api/routes -> services -> repositories -> models`. Services call `integrations/`; routes never do. API responses use a `{success, data, error, meta}` envelope (`app/schemas/common.py`). The schemas are the contract the replacement frontend will be built against. See `docs/architecture.md` for open decisions (database, auth, inbox provider, transcription provider).

## Commands

Each service has a `.env.example`. Copy it to `.env` in the same folder; `.env` is gitignored.

```bash
# backend/
uv sync
uv run fastapi dev app/main.py                        # once main.py has code
uv run pytest                                         # all tests
uv run pytest tests/unit/test_x.py::test_name         # single test
uv run ruff check .

# messaging/ and frontend/
npm install
npm run dev
```

## What Winnie is

Winnie is a coordination agent for the NJIT Women in Computing Society (WiCS) executive board. It addresses these problems:

- Tasks live in several places at once (a task-tracker spreadsheet, Google Docs, Discord). Tasks recorded in one doc don't always reach the tracker, and finished work doesn't always get marked done. Members who depend on that work end up blocked without knowing it.
- Nobody follows up on tasks that get overlooked.
- Handoffs between roles break down. For example, the Treasurer has to order something for an event, but the Event Coordinators haven't passed on the details, and the President needs the event planned by a set date.
- Work isn't rebalanced during busy periods, especially GirlHacks (the annual hackathon). A member having a light week can't easily see where others need help.
- Important emails get lost in a shared inbox that many people use.

## E-Board (12 members)

| Role | Seats |
|---|---|
| President | 1 |
| Vice President | 1 |
| Treasurer | 1 |
| Secretary | 1 |
| Event Coordinator | 2 |
| Industry Partnership Chair | 2 |
| Community Outreach Chair | 1 |
| PR Chair | 2 |
| Technical Director | 1 |

Several roles have two seats, so the data model must handle more than one person per role. A task or notification can target a role, which means every holder, or one specific person, such as "Sponsorship Chair #2".

## Core concepts (from the product spec)

- **Member profile**: name, position, skills, and current and upcoming tasks. The skill list is what lets the system suggest a substitute who can take over another role's task (for example, the Secretary covering a PR task).
- **Task ingestion**: an agent listens to in-person meetings, in the style of Cluely, and pulls out the tasks that come up. It also reads the existing task tracker and meeting agendas, so there is one source of truth instead of many.
- **Timeline / Gantt view**: shows completed, pending and upcoming tasks. Members and the President can check tasks off from it.
- **Deadline monitoring and reassignment**: when a task is coming due or is overdue, or its owner can't do it (time constraints or conflicts), the system notifies the right people and suggests a reassignment. It picks someone with a lighter workload or similar skills, or flags that an AI agent could do the task.
- **Role routing**: questions that don't name an owner go to the person whose role and skills fit.
- **Targeted notifications**: notifications about a finished task go only to the people who care. For example, "sponsorship email sent" notifies the President, the VP and Sponsorship Chair #2, not the whole board.
- **Email triage**: incoming emails in the shared inbox are routed to the right member. If a tagged member hasn't responded after a set time, the system reminds them. For example, it pings the Treasurer about an unanswered budgeting email.
- **Messaging channel**: members use Photon to get notifications and check off tasks in direct messages such as iMessage. Doing this should take as little effort as possible.

## Planned integrations

These are named in the spec. The specific APIs have not been chosen yet:

- Google Sheets (the existing task tracker) and Google Docs (meeting notes and agendas)
- Discord
- The shared email inbox
- Photon, for the iMessage/DM interface
- Meeting audio capture and transcription

## Design notes

- The point of the product is that the whole board sees what everyone is doing. Notifications are targeted, but every task's status, owner and dependencies should be visible to the whole board.
- Dependencies between tasks are a core feature. The failure the club described most was "someone was waiting on work that was already done, or silently stuck." Model dependencies explicitly so that finishing or blocking a task can notify whoever depends on it.
