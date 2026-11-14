# /tasks — the single source of truth for board work.
# TODO:
#   GET   /tasks                              filter by owner, role, status, due window, event (e.g. GirlHacks)
#   POST  /tasks                              create (manual, or confirmed from ingestion)
#   GET   /tasks/{id}                         detail incl. dependencies + dependents
#   PATCH /tasks/{id}                         status change (done / blocked) -> notify dependents
#   POST  /tasks/{id}/dependencies            add a "depends on" edge
#   GET   /tasks/{id}/reassignment-suggestions
#   POST  /tasks/{id}/reassign                accept a suggestion
#   GET   /timeline                           data for the Gantt/timeline view
