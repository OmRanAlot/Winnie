# Event idea to draft task plan

`POST /api/planning/drafts` accepts an idea, event name/type, date and optional
format (`gbm`, `technical_workshop`, `hackathon`, `other`). It returns draft tasks,
suggested roles, date-only deadlines, dependencies, source evidence and open questions.
Dates have no implied time of day. These are proposals, not persisted task records.
There is no approval/activation endpoint or messaging integration in this slice.

## Staged pipeline (preferred)

`POST /api/planning/pipeline-drafts` implements the expanded workflow. The original
`/drafts` route remains compatible and still expects the legacy type labels.
The new route accepts:

```json
{
  "event_name": "Employer-led Git workshop",
  "idea": "A beginner hands-on Git workshop with a company speaker and Q&A",
  "event_date": "2027-04-20",
  "semester_code": "spring-2027"
}
```

`category` is optional; absent a supplied category, a classification specialist
predicts it. The Spring 2027 calendar supplies **14 labeled examples in six categories**:
Tabling, Professional Development, Company Events, Technical Workshop, Destress,
and Alumni Panel Session. It supplies category examples only, not Spring task history.
Undated examples are retained. Explicit labels take precedence over title guesses:
Fiserv and WiCS Gala are Professional Development in this reference.

Mandatory stages:

1. Classify the new idea using the Spring examples, with confidence and source row IDs.
2. Classify every Fall historical event into that taxonomy, or Unknown if unsupported.
3. Retrieve Fall tasks for confidently matching events (threshold 0.65). Join historical
   owners to verified Fall role mappings when available and calculate deadline lead times.
4. Task/role specialist drafts an idea-specific task set. The number of tasks follows
   the requirements; a category is not a fixed task count.
5. Dependency specialist identifies prerequisites and cross-role handoffs with rationale
   and proposed minimum gaps. It distinguishes inferred edges from explicit source evidence.
6. Timeline specialist schedules each task using observed lead days and dependency gaps.
   Unknown or infeasible dates stay null. Effort-hour estimates are separate, inferred values.
7. Deterministic member matching resolves proposed roles against the selected semester's
   verified role holders. Multiple holders remain candidates until one is selected.

These are separate structured Deep Agents calls, orchestrated in Python so every stage
runs in order. This does not rely on a supervisor deciding whether to call a specialist.
The full pipeline is bounded by `WINNIE_PLANNING_PIPELINE_TIMEOUT_SECONDS` (default 180).
Model calls use the same Gemini adapter and credentials described below. Offline mode
only classifies exact labeled names and returns a historical checklist; it does not
pretend to infer new categories, dependencies or schedules.

Responses include classification evidence, historical classifications, task proposals,
schedule rationale, lead-time sample counts/ranges/medians, role-holder candidates,
handoffs and unresolved questions. Invalid citations, missing/duplicate historical IDs,
unknown task references, cycles, reverse phase order, incomplete schedules and violated
dependency gaps fail validation. These are draft records, not live task assignments.
They currently cover dependencies within the proposed event, not links to existing
tasks from other events.

The historical data is a retrieved reference library, not Gemini fine-tuning. First
review the classifications and plan quality; fine-tuning would require a separate
curated dataset and evaluation workflow. We have not trained a model on the calendars.

Prepare the category reference from the supplied Spring CSV (choose a new output name
if the default already exists):

```powershell
python -m app.prepare_pipeline 'C:/path/Spring Calendar.csv' --output data/planning/spring-2027-taxonomy.json
```

Try the full pipeline from `backend/` after configuring Gemini, without a running API:

```powershell
uv run --extra agents python -m app.cli.preview_pipeline --event 'Git workshop' --idea 'Employer-led hands-on Git exercises and Q&A' --date 2027-04-20 --semester spring-2027 --output data/planning/git-draft.json
```

This saves a private review artifact, including proposed Fall classifications, and
does not write to Supabase or send messages. Historical classifications are recomputed
each run for now; there is no reviewed persistent classification cache yet.

### Role-holder data and member pages

The tracker supplies historical assignee names/emails. These establish **who was
assigned the work**, but do not alone establish their board role. The inspected
October cells did not expose an explicit person-to-role legend. The importer can now
retain owner text in private context; it strips it from model context after joining
verified role labels. Unresolved historical roles remain unknown.

For matching, configure `WINNIE_PLANNING_ROSTER_PATH` to a private JSON file with this
shape (synthetic example):

```json
{
  "rosters": [{
    "semester_code": "fall-2026",
    "verified_by": "Board administrator",
    "members": [{
      "member_code": "EXAMPLE_EC1",
      "display_name": "Example Coordinator",
      "roles": ["Event Coordinator"],
      "aliases": ["coordinator@example.test"],
      "active": true
    }]
  }]
}
```

Use real verified member codes from the existing member system. Multiple people can
hold one role and one person can hold several roles. Historical role mappings and
current role holders are semester-specific; no Spring task tracker is required to
maintain a Spring roster. Owner proposals remain null if a matching roster is missing.
The matcher does not infer availability, silently balance work, or select one of two
coordinators. Open-task counts may be recorded but do not currently drive selection.

Member-page writes remain a separate integration: persist and review the proposal,
approve its exact revision, then create owner-linked canonical tasks with dependency
records and expose them through the authenticated member task query. The current
frontend is a recorder and has no member task pages to populate. The model has no
write/send tools and cannot bypass that activation flow.

## Historical context

The supplied Fall 2026 event calendar was matched against the Fall tracker's
`October 2026` tab, gid `1107311783`, read on November 14, 2026.
That monthly snapshot includes tasks from August through December; it is not an
October-only task list. Only event names, task titles, historical deadlines and
permanent source task IDs and optional historical assignee text are retained in
private local context. Attendance, completion status and notes are excluded.
Unresolved assignee text is excluded from model context. Historical deadlines are
precedents, never copied into the new draft automatically.

Reviewed aliases:

| Tracker group | Calendar event |
|---|---|
| Involvement Fair | Student Involvement Fair |
| WiCS Tech Workshop 1 | WiCS Technical Workshop |
| Verizon Event | Verizon Info Session |

GBM 1/2/3 match by name. Six of 13 named calendar events have matching tasks.
Examples cover table signup/marketing, GBM preparation and follow-up, workshop
materials, and company logistics. GirlHacks, the collaboration events and several
other calendar entries have no matching tasks in this snapshot. A broad `WiCS`
category is insufficient: retrieval separates GBMs, technical workshops and hackathons.
Unmatched tracker groups such as Elections and Mentorship Chats remain unjoined;
they are not silently treated as tasks for an unrelated calendar event.

The source files and generated context stay in gitignored `backend/data/planning/`.
Fresh checkouts must prepare their own context. To rebuild from exported CSVs,
run from `backend/`, using a new output filename:

```powershell
python -m app.prepare_planning 'C:/path/calendar.csv' 'C:/path/October.csv' --year 2026 --spreadsheet-id YOUR_ID --tab 'October 2026' --output data/planning/fall-2026.json
```

The tracker CSV must include Event, Task Name, Deadline and Winnie Task ID.
The builder refuses to overwrite an existing context file. Multi-day event date
text is preserved; the historical start date is used for context. The current draft
request represents one event date, so split multi-day programs into separate drafts
until interval planning is added. Refreshing Google Sheets is a separate operation;
this endpoint only reads the prepared local file.

## Run locally

The default `WINNIE_PLANNING_MODE=mock` requires no model key. It produces a
deduplicated historical checklist with unknown dates/roles and **does not reason
about the idea**. It is intended for wiring up review screens and offline tests.

For idea-specific generation, install the optional dependencies from `backend/`:

```powershell
uv sync --extra agents
```

Set these in the repository-root `.env`, then restart the API:

```dotenv
WINNIE_PLANNING_MODE=deepagents
WINNIE_PLANNING_MODEL=google_genai:gemini-4-hydrogen
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
WINNIE_PLANNING_KNOWLEDGE_PATH=backend/data/planning/fall-2026.json
WINNIE_PLANNING_TIMEOUT_SECONDS=60
```

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey).
The adapter reads `GEMINI_API_KEY` directly from the root `.env`; no shell export
is needed. `GOOGLE_API_KEY` is also accepted and takes precedence if both are set.
The adapter explicitly selects the Gemini Developer API, so Vertex AI project,
region and service-account setup are unnecessary for this path. Use a model ID
enabled for your project; see [Google's model list](https://aistudio.google.com/docs/models).

LangChain and Deep Agents run as Python libraries; they require no separate hosted
account or LangChain API key. LangSmith tracing is optional and disabled unless you
configure it in the process environment. We do not enable tracing by default.

The agents extra installs both Google and OpenAI integrations. For OpenAI, set
`WINNIE_PLANNING_MODEL=openai:YOUR_MODEL_ID` and export `OPENAI_API_KEY` in the API
process environment. Other providers need their corresponding integration package.

Use `/docs` to try this request. Supply `X-Winnie-API-Key` when the existing task
API key is configured; production fails closed without that configuration.

```json
{
  "event_name": "Spring Git workshop",
  "event_type": "Company",
  "event_date": "2027-04-20",
  "idea": "An employer-led beginner Git workshop with hands-on exercises and Q&A"
}
```

The Deep Agents adapter performs requirement extraction, role suggestions and
timeline/dependency reasoning within one structured agent run. It uses LangChain's
`create_deep_agent(response_format=...)` and a virtual `StateBackend`; it receives
no host filesystem, shell, task storage, booking or message-sending tools.
See the [Deep Agents API reference](https://reference.langchain.com/python/deepagents/graph/create_deep_agent)
and [backend documentation](https://docs.langchain.com/oss/python/deepagents/backends).

The service checks evidence membership, unique task IDs, known dependencies,
dependency cycles, dependency date ordering and deadlines relative to event phase.
Missing dates stay null. Roles are proposals, with no inferred person/availability.
Source cells are untrusted data in the model instructions. Provider failures return
a generic error without exposing prompts or keys. Model output never becomes an
active assignment. Runs have no durable checkpointer or cross-run memory.

## Next integration

Persist and edit proposal revisions, implement President approval, resolve roles
against actual member capacity, then activate the exact approved tasks through the
task service. Do not turn this draft route into a direct task writer.
