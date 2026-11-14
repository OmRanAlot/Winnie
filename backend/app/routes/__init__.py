"""HTTP endpoints. One module per feature; each exposes `router = APIRouter(prefix="/api/...")`.

Register a new router in app/main.py. Keep handlers thin: validate input, call a function in
services/, return the result. Never call integrations/ from here.

BUILT
    health.py      GET  /api/health
    recordings.py  POST /api/recordings   (save a browser recording: audio + transcript JSON)

PLANNED (create the file when you build the feature)
    tasks.py          /api/tasks - the single source of truth for board work
                        GET   /tasks            filter by owner, role, status, due window, event (e.g. GirlHacks)
                        POST  /tasks            create (manual, or confirmed from ingestion)
                        GET   /tasks/{id}       detail incl. dependencies + dependents
                        PATCH /tasks/{id}       status change (done / blocked) -> notify dependents
                        POST  /tasks/{id}/dependencies          add a "depends on" edge
                        GET   /tasks/{id}/reassignment-suggestions
                        POST  /tasks/{id}/reassign              accept a suggestion
                        GET   /timeline         data for the Gantt/timeline view
    members.py        /api/members and /api/roles
                        GET   /members          list with a current-workload summary
                        GET   /members/{id}     name, role seat(s), skills, current + upcoming tasks
                        PATCH /members/{id}     update skills / availability (busy weeks, conflicts)
                        GET   /roles            roles with seat holders ("PR Chair #1", "PR Chair #2")
                        GET   /roles/{id}/members   resolve a role target to every holder
    ingestion.py      /api/ingestion - pulling tasks out of meetings and existing docs
                        POST /ingestion/meetings                 audio / transcript -> task candidates
                        POST /ingestion/sync/task-tracker        pull the Google Sheets tracker
                        POST /ingestion/sync/docs                scan meeting notes / agendas in Google Docs
                        GET  /ingestion/candidates               extracted tasks awaiting human confirmation
                        POST /ingestion/candidates/{id}/confirm  (and /reject)
    notifications.py  /api/notifications - targeted: only the people who care
                        GET  /notifications?member_id=     a member's inbox
                        POST /notifications/{id}/ack
                        GET  /notifications/subscriptions  who is notified about what (role- or person-targeted)
    email.py          /api/email - shared-inbox triage
                        GET  /email/threads                triaged threads with assignee + response status
                        POST /email/threads/{id}/assign    manual routing override
                        POST /email/threads/{id}/resolve   mark responded (stops reminders)
    webhooks.py       /api/webhooks - inbound events from other services
                        POST /webhooks/messaging  from messaging/ (Photon DMs: "done", "blocked", questions).
                                                  Verify the MESSAGING_WEBHOOK_SECRET signature first.
                        POST /webhooks/email      new shared-inbox mail, if the provider pushes
"""
