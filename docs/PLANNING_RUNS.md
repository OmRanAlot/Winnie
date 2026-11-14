# Durable event planning and review

The existing five Deep Agents specialists now run inside a persistent LangGraph
workflow: generation followed by a human-review interrupt. This adds recovery and
review to the staged planner without granting a model task-writing or messaging tools.

## Behavior

- Every new run has a stable UUID used as its LangGraph `thread_id`.
- Successful specialist responses are saved locally. A retry reuses responses for
  the same stage, schema and input; it runs the interrupted stage again.
- Invalid dependency/scheduling responses are discarded when correction feedback
  is issued. A failed final response is also discarded so retries can recover.
- The completed draft is checkpointed, then LangGraph's `interrupt()` pauses review.
- Approval/rejection resumes the graph with `Command(resume=...)`. Review does not
  rerun generation and requires the exact SHA-256 revision of the saved draft.
- Repeating the same decision/revision returns its existing result. Conflicting or
  stale decisions fail with HTTP 409.
- Changes to source snapshots, role data, prompts, schemas or planning-policy code
  invalidate recovery/review. Start a new run to generate against the new context.
- Reviews are recorded separately from the draft. **Approved means reviewed; it
  does not activate tasks, write to Supabase, or send notifications.**

An actual new-Python-process test covers both interrupted generation recovery and
resumption of a saved review interrupt. Tests use the real SQLite checkpointer and
fake specialists, with no provider calls.

## Local setup

From `backend/`, install the current dependencies:

```powershell
uv sync --extra agents
```

Keep the existing Gemini and planning-context settings from
[EVENT_PLANNING.md](EVENT_PLANNING.md). Add these in the root or backend `.env`:

```dotenv
WINNIE_PLANNING_RUNS_PATH=backend/data/planning/runs.sqlite3
WINNIE_PLANNING_PIPELINE_TIMEOUT_SECONDS=420
WINNIE_PLANNING_REVIEW_API_KEY=YOUR_SEPARATE_RANDOM_REVIEW_SECRET
```

Restart FastAPI after changing settings. Generation uses the existing task API
access policy (`X-Winnie-Api-Key` when configured; production fails closed when
it is missing). Approval/rejection additionally requires
`X-Winnie-Planning-Review-Key`. Review fails closed without its own configured key,
including in development. Never put either secret in a URL.

The review key authorizes a local reviewer; it does not establish an individual
President identity. Verified per-user approval authorization must be added before
multi-user deployment.

## HTTP workflow

1. `POST /api/planning/runs` with this body returns HTTP 202 and a run ID. Generation
   starts in the API's background task; it does not block the response.

   ```json
   {
     "event_name": "Employer-led Git workshop",
     "idea": "A hands-on beginner workshop with a company speaker and Q&A",
     "event_date": "2027-04-20",
     "semester_code": "spring-2027"
   }
   ```

2. Poll `GET /api/planning/runs/{id}`. Status progresses from `queued` to `running`
   to `waiting_for_review` (or `failed`). The result includes stage progress, the
   complete draft, warnings, and its immutable `revision`.

3. Review the tasks, roles, dates, evidence and dependencies. Submit
   `POST /api/planning/runs/{id}/review` with the extra review-key header:

   ```json
   {
     "decision": "approve",
     "expected_revision": "COPY_THE_EXACT_REVISION_FROM_GET",
     "note": "Reviewed the proposed roles, deadlines and prerequisites."
   }
   ```

   `decision` can be `approve` or `reject`. The response still says `activated: false`.
   Draft editing is not exposed yet; reject and start a new run with clarified input.

4. After an interrupted/failed generation, use
   `POST /api/planning/runs/{id}/resume`. Previously completed specialist results are
   reused. A provider call interrupted before its response was saved can repeat.

The existing `/api/planning/drafts` and `/api/planning/pipeline-drafts` routes remain
compatible and ephemeral. Use `/runs` for persisted generation and review.

## Terminal workflow

From `backend/`:

```powershell
uv run --extra agents python -m scripts.planning_run create --event 'Git workshop' --idea 'Employer-led Git exercises and Q&A' --date 2027-04-20 --semester spring-2027 --run
uv run --extra agents python -m scripts.planning_run show RUN_UUID
uv run --extra agents python -m scripts.planning_run resume RUN_UUID
```

`create` without `--run` only creates a queued record. CLI generation prints the
saved draft and revision at the review pause. Use the protected HTTP route to decide.

## Persistence and operating limits

The configured path stores run records, progress and specialist results. A sibling
file, `runs.checkpoints.sqlite3`, stores LangGraph state. The files are deliberately
separate to avoid lock contention between async checkpoint writes and synchronous
progress writes. Keep both, plus SQLite's associated journal files, together when
backing up a stopped local API. They contain private event context and stay under
gitignored `data/`; credentials are never stored in run context or returned by the API.

Generation has a 660-second lease that prevents duplicate workers. After a hard
process crash, wait for the abandoned lease to expire before resuming. Normal
failures/cancellations release the lease immediately.

This is a single-host development implementation. Background tasks run inside the
API process; queued/running jobs are not automatically redispatched on startup.
Use `/resume` after a restart. Production still needs a worker/job queue, a production
checkpointer such as PostgreSQL, retention rules and verified reviewer identity.
The individual Deep Agents calls keep their existing virtual StateBackend; the
outer workflow checkpoints proposal/review state, and the stage cache preserves
completed responses. It cannot resume halfway through an unfinished model call.

The next integration is an approval-to-activation service that writes the approved
tasks/dependencies once, maps owners to canonical members, and exposes them on the
dashboard. It must use the existing task services and authorization rules.
