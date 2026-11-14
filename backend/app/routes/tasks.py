"""Task CRUD endpoints for the dashboard and backend clients; delegates to services/tasks.py."""

from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.integrations.supabase import StorageUnavailable
from app.services.tasks import TaskNotFound, TaskStore
from app.settings import Settings
from app.task_schemas import (
    MonthCode,
    SemesterCode,
    StakeholderCode,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
)


def authorize_tasks(x_winnie_api_key: str = Header(default="")):
    settings = Settings()
    expected = settings.task_api_key.get_secret_value()
    if not expected:
        if settings.environment != "development":
            raise HTTPException(503, "Configure WINNIE_TASK_API_KEY before exposing tasks.")
        return
    if not compare_digest(x_winnie_api_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid task API key.")


router = APIRouter(
    prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(authorize_tasks)]
)


def get_task_store():
    return TaskStore()


Store = Annotated[TaskStore, Depends(get_task_store)]


def envelope(data, meta=None):
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def run_operation(operation, meta=None):
    try:
        return envelope(operation(), meta)
    except TaskNotFound:
        return JSONResponse(status_code=404, content={
            "success": False, "data": None,
            "error": {"message": "Task not found."}, "meta": {},
        })
    except StorageUnavailable:
        return JSONResponse(status_code=503, content={
            "success": False, "data": None,
            "error": {"message": "Task storage is unavailable. Check Supabase configuration."},
            "meta": {},
        })


@router.post("", status_code=201)
def create_task(task: TaskCreate, store: Store):
    return run_operation(lambda: store.create(task))


@router.get("")
def list_tasks(
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


@router.get("/{task_id}")
def get_task(task_id: UUID, store: Store):
    return run_operation(lambda: store.get(task_id))


@router.patch("/{task_id}")
def update_task(task_id: UUID, changes: TaskUpdate, store: Store):
    return run_operation(lambda: store.update(task_id, changes))


@router.delete("/{task_id}")
def delete_task(task_id: UUID, store: Store):
    def operation():
        store.delete(task_id)
        return {"id": str(task_id)}

    return run_operation(operation)
