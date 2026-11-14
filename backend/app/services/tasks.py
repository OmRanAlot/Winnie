"""Task use cases, in two groups sharing one module (routes/tasks.py is the only caller).

Timeline (repository.py, bigint ids): save a meeting's extracted tasks, list them for the Gantt
view, check off. Errors are left to the caller: repository.NotFound, ValueError, STORAGE_ERRORS.

Task records (TaskStore, uuid ids): CRUD against the Supabase `tasks` table via
integrations/supabase.py. Raises TaskNotFound / StorageUnavailable.
"""

from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

import httpx
from httpx import HTTPError
from postgrest.exceptions import APIError

from app import repository
from app.integrations.supabase import StorageUnavailable, create_task_client
from app.integrations.supabase_client import SupabaseNotConfigured
from app.models import ExtractedTask, Task
from app.schemas import TaskView
from app.task_schemas import TaskCreate, TaskUpdate

# Anything that means "the task store could not be reached or is not set up".
STORAGE_ERRORS = (SupabaseNotConfigured, APIError, httpx.HTTPError)

# --- Timeline (repository-backed) ----------------------------------------


def to_view(task: Task) -> TaskView:
    return TaskView(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        seat=task.seat,
        assignee=task.assignee,
        assignee_id=task.assignee_id,
        start=task.meeting_held_at or task.created_at,
        end=task.deadline_at,
        deadline_raw=task.deadline_raw,
        needs_review=task.needs_review,
        rationale=task.rationale,
        depends_on=list(task.depends_on),
    )


class StoredTasks(NamedTuple):
    tasks: list[TaskView]
    reused: bool  # True when this recording's tasks were already stored (a retry)


def store_meeting_tasks(
    recording_id: str,
    held_at: datetime,
    title: str | None,
    transcript: str | None,
    tasks: list[ExtractedTask],
) -> StoredTasks:
    """Store a recording's meeting and tasks once. Returns them as timeline views.

    Idempotent per recording: if its meeting already has tasks (e.g. the user retried after a
    timeout), those are returned and nothing is inserted, so the board never gets duplicates.
    A meeting left without tasks by an earlier failed insert is filled now.
    """
    meeting_id, created = repository.find_or_create_meeting(held_at, title, transcript, recording_id)
    if not created and (existing := repository.tasks_for_meeting(meeting_id)):
        return StoredTasks([to_view(task) for task in existing], reused=True)
    stored = repository.insert_extracted_tasks(meeting_id, tasks)
    return StoredTasks([to_view(task) for task in stored], reused=False)


def list_task_views(
    status: str | None = None, assignee: str | None = None, seat: str | None = None
) -> list[TaskView]:
    tasks = repository.list_tasks(status=status, assignee=assignee, seat=seat)
    return [to_view(task) for task in tasks]


def set_status(task_id: int, status: str) -> TaskView:
    return to_view(repository.update_task_status(task_id, status))


# --- Task records (TaskStore, uuid-backed) ----------------------------------


class TaskNotFound(Exception):
    pass


class TaskStore:
    def __init__(self, client_factory: Callable = create_task_client):
        self.client_factory = client_factory

    def _execute(self, operation):
        client = None
        try:
            client = self.client_factory()
            return operation(client.table("tasks")).execute()
        except (HTTPError, APIError) as exc:
            # Do not expose provider errors, URLs, or credentials through the API.
            raise StorageUnavailable("Task storage is unavailable.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()

    def create(self, task: TaskCreate):
        result = self._execute(lambda table: table.insert(task.model_dump(mode="json")))
        return result.data[0]

    def list(self, *, month_code=None, status=None, stakeholder_code=None, limit=50, offset=0):
        def query(table):
            request = table.select("*", count="exact")
            if month_code is not None:
                request = request.eq("month_code", month_code)
            if status is not None:
                request = request.eq("status", status)
            if stakeholder_code is not None:
                request = request.contains("stakeholder_codes", [stakeholder_code])
            return request.order("created_at", desc=True).order("id").range(
                offset, offset + limit - 1
            )

        result = self._execute(query)
        return result.data, result.count

    def get(self, task_id: UUID):
        result = self._execute(lambda table: table.select("*").eq("id", str(task_id)))
        if not result.data:
            raise TaskNotFound
        return result.data[0]

    def update(self, task_id: UUID, changes: TaskUpdate):
        result = self._execute(
            lambda table: table.update(changes.model_dump(mode="json", exclude_unset=True)).eq(
                "id", str(task_id)
            )
        )
        if not result.data:
            raise TaskNotFound
        return result.data[0]

    def delete(self, task_id: UUID):
        result = self._execute(lambda table: table.delete().eq("id", str(task_id)))
        if not result.data:
            raise TaskNotFound
