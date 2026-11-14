"""Task endpoints, in two groups on one /api/tasks router.

Timeline (read by the frontend's Gantt view, frontend/src/lib/api.ts), bigint ids, no auth yet:
    GET   /api/tasks?status=&assignee=&seat=   every task, ordered by deadline (unscheduled last)
    PATCH /api/tasks/{task_id}/status          body {"status": "open" | "done" | "blocked"}

Task records (CRUD for backend clients), uuid ids, require the X-Winnie-Api-Key header:
    POST/GET /api/tasks/records, GET/PATCH/DELETE /api/tasks/records/{task_id}

Thin: validates input, calls services/tasks.py, wraps results in the {success, data, error, meta}
envelope.
"""

import logging
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app import repository
from app.integrations.supabase import StorageUnavailable
from app.schemas import TaskStatusUpdate, failure
from app.services import tasks as task_service
from app.services.tasks import TaskNotFound, TaskStore
from app.settings import Settings
from app.task_schemas import MonthCode, StakeholderCode, TaskCreate, TaskStatus, TaskUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

STORE_UNAVAILABLE = "The task store is unavailable. Check the Supabase settings and try again."


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
def update_status(task_id: int, body: TaskStatusUpdate):
    try:
        view = task_service.set_status(task_id, body.status)
    except repository.NotFound:
        return failure("Task not found.", 404)
    except task_service.STORAGE_ERRORS:
        logger.exception("Could not update task %s", task_id)
        return failure(STORE_UNAVAILABLE, 503)
    return {"success": True, "data": view.model_dump(mode="json"), "error": None, "meta": {}}


# --- Task records ---------------------------------------------------------


def authorize_tasks(x_winnie_api_key: str = Header(default="")):
    settings = Settings()
    expected = settings.task_api_key.get_secret_value()
    if not expected:
        if settings.environment != "development":
            raise HTTPException(503, "Configure WINNIE_TASK_API_KEY before exposing tasks.")
        return
    if not compare_digest(x_winnie_api_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid task API key.")


records = APIRouter(prefix="/records", dependencies=[Depends(authorize_tasks)])


def get_task_store():
    return TaskStore()


Store = Annotated[TaskStore, Depends(get_task_store)]


def envelope(data, meta=None):
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def run_operation(operation, meta=None):
    try:
        return envelope(operation(), meta)
    except TaskNotFound:
        return failure("Task not found.", 404)
    except StorageUnavailable:
        return failure("Task storage is unavailable. Check Supabase configuration.", 503)


@records.post("", status_code=201)
def create_task(task: TaskCreate, store: Store):
    return run_operation(lambda: store.create(task))


@records.get("")
def list_task_records(
    store: Store,
    month_code: MonthCode | None = None,
    status: TaskStatus | None = None,
    stakeholder_code: StakeholderCode | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
):
    meta = {"limit": limit, "offset": offset}

    def operation():
        tasks, total = store.list(
            month_code=month_code, status=status, stakeholder_code=stakeholder_code,
            limit=limit, offset=offset,
        )
        meta["total"] = total
        return tasks

    return run_operation(operation, meta)


@records.get("/{task_id}")
def get_task(task_id: UUID, store: Store):
    return run_operation(lambda: store.get(task_id))


@records.patch("/{task_id}")
def update_task(task_id: UUID, changes: TaskUpdate, store: Store):
    return run_operation(lambda: store.update(task_id, changes))


@records.delete("/{task_id}")
def delete_task(task_id: UUID, store: Store):
    def operation():
        store.delete(task_id)
        return {"id": str(task_id)}

    return run_operation(operation)


router.include_router(records)
