"""Pydantic shapes for what crosses a boundary: HTTP, or the planning agents' structured output.

    api.py        Browser Recording, TaskView, TaskStatusUpdate and the {success, data, error,
                  meta} response envelope (failure()). The contract the frontend is built on.
    tasks.py      Task-store request/response shapes: TaskCreate, TaskUpdate, tracker codes.
    planning.py   Event-planning drafts: PlanningRequest, ProposedTask, DraftContents, PlanningDraft.
    pipeline.py   Staged planning pipeline: PipelineRequest, Classification, Dependencies,
                  Schedule, PipelineDraft, and the roster file shape.

Import from the module that defines a shape (from app.schemas.tasks import TaskCreate). This
file deliberately re-exports nothing, so importing one shape never loads the others. Stored
domain objects live in domain/models.py, not here.
"""
