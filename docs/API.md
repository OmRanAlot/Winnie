# API contract plan

Only `GET /api/health` is implemented today. All other routes below are proposed integration contracts. FastAPI's generated `/docs` and `/openapi.json` become the authoritative implemented schemas as routes land.

## Conventions

- Prefix routes with `/api`. JSON uses snake_case, stable string IDs, UTC ISO-8601 timestamps, and explicit event timezone fields.
- List responses use `{ "items": [...] }`; add pagination before loading significant real history.
- Validate input with Pydantic. Use 401 for missing identity, 403 for insufficient permission, 404 for unavailable resources, 409 for stale revisions or conflicting transitions, and 422 for invalid payloads.
- Use FastAPI's `detail` field for errors, with a stable machine-readable error code when domain routes are introduced.
- All writes require an authenticated actor or verified provider identity. Local mock-only demo identity must be explicit and disabled for real integrations.
- Treat approvals, inbound provider events, and delivery retries as idempotent operations. Do not rely on browser button disabling for correctness.

## Proposed routes

| Method | Route | Responsibility |
| --- | --- | --- |
| GET | `/health` | Implemented process health: `{"status":"ok","service":"winnie-api"}` |
| GET | `/members` | Board profiles and workload summaries; omit private messaging identifiers |
| GET | `/events` | Events visible to actor |
| POST | `/events` | Create a draft event with date/time and timezone |
| GET | `/events/{event_id}` | Event details |
| POST | `/transcripts` | Store authorized text and consent metadata linked to event |
| POST | `/events/{event_id}/plans` | Start a draft run using prompt + transcript IDs; return 202 + run ID |
| GET | `/runs/{run_id}` | Poll queued/running/waiting_for_approval/completed/failed run and proposal reference |
| GET | `/plans/{plan_id}` | Structured proposal, revision, warnings, evidence |
| PATCH | `/plans/{plan_id}` | President edits proposed tasks with expected revision |
| POST | `/plans/{plan_id}/approve` | President activates exact revision once; queue assignments |
| POST | `/plans/{plan_id}/reject` | President rejects exact revision with optional reason |
| GET | `/tasks?event_id=...&owner_id=...` | Canonical task list |
| PATCH | `/tasks/{task_id}` | Authorized status/correction update with expected version; ownership changes use approval flow |
| GET | `/notifications` | Authorized delivery status; mock outbox for local demo |
| POST | `/webhooks/messages` | Provider-verified inbound messages, if chosen Photon API supports webhooks |

If Photon uses streaming, the integration bridge calls an authenticated internal ingestion interface instead of a public provider webhook. Do not expose arbitrary notification send or clock-advance routes publicly. Scheduled scans run inside the worker; demo time controls remain local/test-only.

## Example planned proposal payload

```json
{
  "id": "plan-example",
  "event_id": "event-example",
  "revision": 1,
  "status": "pending_approval",
  "warnings": [],
  "tasks": [
    {
      "id": "task-materials",
      "title": "Create workshop materials list",
      "owner_id": "member-event-coordinator-1",
      "due_at": "2027-04-09T21:00:00Z",
      "estimated_effort_hours": 1,
      "dependency_ids": [],
      "rationale": "Event coordination role and available capacity",
      "evidence": [{"transcript_id": "transcript-example", "quote": "We need a materials list before the Treasurer can order."}]
    },
    {
      "id": "task-purchase",
      "title": "Order workshop materials",
      "owner_id": "member-treasurer",
      "due_at": "2027-04-12T21:00:00Z",
      "estimated_effort_hours": 1,
      "dependency_ids": ["task-materials"],
      "rationale": "Treasurer handles approved purchases",
      "evidence": [{"transcript_id": "transcript-example", "quote": "We need a materials list before the Treasurer can order."}]
    }
  ]
}
```

Dates, identities, IDs, and quotes above are synthetic contract examples. An agent's rationale is advisory; backend rules and President approval decide activation. The approval request should include `expected_revision` and return the activated event/task references. Repeating approval for the same approved revision returns that same result.
