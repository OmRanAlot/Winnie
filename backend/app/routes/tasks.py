"""Task endpoints, in two groups on one /api/tasks router.

Timeline compatibility view, UUID ids, approved Supabase membership required:
    GET   /api/tasks?status=&assignee=&seat=   every task, ordered by deadline (unscheduled last)
    PATCH /api/tasks/{task_id}/status          body {"status": "todo" | "in_progress" | "done" | "blocked"}

Task records (CRUD for backend clients), uuid ids, verified Bearer token or scoped server key:
    POST/GET /api/tasks/records, GET/PATCH/DELETE /api/tasks/records/{task_id}
    POST /api/tasks/records/dependencies (admin-only, cycle-checked batch insert)

Thin: validates input, calls services/tasks.py, wraps results in the {success, data, error, meta}
envelope.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.auth import Principal, require_admin, require_member
from app.core.settings import Settings
from app.db import repository
from app.integrations.supabase import StorageUnavailable
from app.schemas.api import TaskStatusUpdate, failure
from app.schemas.tasks import (
    MonthCode,
    SemesterCode,
    StakeholderCode,
    TaskCreate,
    TaskDependencyBatch,
    TaskStatus,
    TaskUpdate,
)
from app.services import tasks as task_service
from app.services.members import MemberStore
from app.services.task_permissions import update_authorized
from app.services.tasks import TaskChanged, TaskNotFound, TaskStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

STORE_UNAVAILABLE = "The task store is unavailable. Check the Supabase settings and try again."


def get_task_store():
    return TaskStore()


def get_task_members():
    return MemberStore()


Store = Annotated[TaskStore, Depends(get_task_store)]
Members = Annotated[MemberStore, Depends(get_task_members)]
Actor = Annotated[Principal, Depends(require_member)]


# --- Timeline -------------------------------------------------------------


@router.get("")
def list_tasks(status: str | None = None, assignee: str | None = None, seat: str | None = None):
    try:
        views = task_service.list_task_views(status=status, assignee=assignee, seat=seat)
    except repository.InvalidStatus as error:
        return failure(str(error), 422)
    except task_service.STORAGE_ERRORS:
        logger.exception("Could not list tasks")
        return failure(STORE_UNAVAILABLE, 503)
    return {
        "success": True,
        "data": [view.model_dump(mode="json") for view in views],
        "error": None,
        "meta": {"count": len(views)},
    }


@router.patch("/{task_id}/status")
def update_status(task_id: UUID, body: TaskStatusUpdate, store: Store, members: Members, actor: Actor):
    try:
        status = "todo" if body.status == "open" else body.status
        saved = update_authorized(task_id, TaskUpdate(status=status), actor, store, members)
        view = task_service.to_view(repository.task_from_record(saved))
    except (repository.NotFound, TaskNotFound):
        return failure("Task not found.", 404)
    except TaskChanged:
        return failure("Task changed. Refresh and try again.", 409)
    except (*task_service.STORAGE_ERRORS, StorageUnavailable):
        logger.exception("Could not update task %s", task_id)
        return failure(STORE_UNAVAILABLE, 503)
    return {"success": True, "data": view.model_dump(mode="json"), "error": None, "meta": {}}


# --- Task records ---------------------------------------------------------


authorize_tasks = require_member


records = APIRouter(prefix="/records", dependencies=[Depends(authorize_tasks)])


def envelope(data, meta=None):
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def run_operation(operation, meta=None):
    try:
        return envelope(operation(), meta)
    except TaskNotFound:
        return failure("Task not found.", 404)
    except TaskChanged:
        return failure("Task changed. Refresh and try again.", 409)
    except StorageUnavailable:
        return failure("Task storage is unavailable. Check Supabase configuration.", 503)


@records.post("", status_code=201, dependencies=[Depends(require_admin)])
def create_task(task: TaskCreate, store: Store):
    if task.semester_code is None:
        task = task.model_copy(update={"semester_code": Settings().active_semester})
    return run_operation(lambda: store.create(task))


@records.get("")
def list_task_records(
    store: Store,
    month_code: MonthCode | None = None,
    semester_code: SemesterCode | None = None,
    status: TaskStatus | None = None,
    stakeholder_code: StakeholderCode | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
):
    meta = {"limit": limit, "offset": offset}

    def operation():
        tasks, total = store.list(
            month_code=month_code, semester_code=semester_code,
            status=status, stakeholder_code=stakeholder_code,
            limit=limit, offset=offset,
        )
        meta["total"] = total
        return tasks

    return run_operation(operation, meta)


@records.get("/{task_id}")
def get_task(task_id: UUID, store: Store):
    return run_operation(lambda: store.get(task_id))


@records.patch("/{task_id}")
def update_task(task_id: UUID, changes: TaskUpdate, store: Store, members: Members, actor: Actor):
    return run_operation(lambda: update_authorized(task_id, changes, actor, store, members))


@records.post("/dependencies", dependencies=[Depends(require_admin)])
def add_task_dependencies(body: TaskDependencyBatch):
    pairs = [(str(edge.task_id), str(edge.depends_on_id)) for edge in body.edges]
    try:
        added = task_service.add_dependencies(pairs)
    except repository.NotFound as error:
        return failure(str(error), 404)
    except ValueError as error:
        return failure(str(error), 422)
    except task_service.STORAGE_ERRORS:
        logger.exception("Could not save inferred task dependencies")
        return failure(STORE_UNAVAILABLE, 503)
    return envelope({
        "edges": [edge.model_dump(mode="json") for edge in added],
        "added": len(added),
    })


@records.delete("/{task_id}", dependencies=[Depends(require_admin)])
def delete_task(task_id: UUID, store: Store):
    def operation():
        store.delete(task_id)
        return {"id": str(task_id)}

    return run_operation(operation)


class _EventLabelTask(BaseModel):
    id: str
    title: str
    description: str = ""


class _EventLabelsRequest(BaseModel):
    tasks: list[_EventLabelTask]


@records.post("/event-labels")
async def suggest_event_labels(body: _EventLabelsRequest):
    settings = Settings()
    if not settings.gemini_api_key:
        return failure("Gemini is not configured. Set GEMINI_API_KEY.", 503)
    try:
        labels = await task_service.suggest_event_labels(
            [t.model_dump() for t in body.tasks],
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
        )
        return envelope(labels)
    except Exception:
        logger.exception("Event label suggestion failed")
        return failure("Could not suggest event labels.", 502)


router.include_router(records)
