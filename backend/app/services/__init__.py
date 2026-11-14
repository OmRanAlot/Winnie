"""Business logic. Called by routes/ and (later) jobs. No HTTP or FastAPI objects in here.

Services own the rules: approve plans, update tasks, resolve text replies, calculate reminders,
validate dependencies, pick notification recipients. Anything an agent does must go through these
same functions, never around them.

BUILT
    recordings.py   save_recording(): write a validated browser recording to backend/data/recordings/

PLANNED (create the file when you build the feature)
    tasks.py          Task lifecycle and the dependency graph.
                        - create / update / mark done or blocked; on a status change, hand the
                          dependents to notifications.py.
                        - add/remove dependency edges, reject cycles, answer "who is waiting on this?"
                          and "what is silently stuck?" (blocked chains, done-but-not-propagated work).
    notifications.py  Targeted notifications. Resolve targets (role -> every seat, seat -> one person),
                      apply subscription rules, pick a channel, send via integrations/.
    deadlines.py      Find tasks due soon / overdue / whose owner is unavailable; trigger notifications
                      and reassignment suggestions. Reassignment picks a lighter workload or matching
                      skills, or flags the task as AI-doable. Matters most during the GirlHacks crunch.
                      Run periodically by the worker (see app/__init__.py, "jobs.py").
    ingestion.py      Turn raw sources into task candidates: meeting transcripts, the Sheets tracker,
                      Docs agendas/notes, Discord. De-duplicate against existing tasks so there is
                      one source of truth.
    email_triage.py   Classify new shared-inbox mail, route it to the member whose role + skills fit
                      best, and schedule a reminder when they have not replied within
                      EMAIL_REMINDER_AFTER_HOURS. The same role routing answers un-owned DM questions.
    messaging.py      Handle DM commands forwarded by messaging/: "done <task>",
                      "blocked <task> because ...", "what's on my plate?".
"""
