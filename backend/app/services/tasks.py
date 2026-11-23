"""Task use cases, in two groups sharing one module (routes/tasks.py is the only caller).

Timeline (repository.py, UUID ids): save a meeting's extracted tasks, list them for the Gantt
view, check off. Errors are left to the caller: repository.NotFound, ValueError, STORAGE_ERRORS.

Task records (TaskStore, UUID ids): CRUD against the Supabase `tasks` table via
integrations/supabase.py. Raises TaskNotFound / StorageUnavailable.
"""

from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

import httpx
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.db import repository
from app.domain.models import ExtractedTask, Task, TaskDependency
from app.integrations.supabase import StorageUnavailable, create_task_client
from app.integrations.supabase_client import SupabaseNotConfigured
from app.schemas.api import TaskView
from app.schemas.tasks import TaskCreate, TaskUpdate

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
    existing = [] if created else repository.tasks_for_meeting(meeting_id)
    # Only skip re-insertion when we got the same or more tasks last time; a prior
    # partial extraction (fewer tasks than now) is replaced by the new full result.
    if existing and len(existing) >= len(tasks):
        return StoredTasks([to_view(task) for task in existing], reused=True)
    stored = repository.insert_extracted_tasks(meeting_id, tasks)
    return StoredTasks([to_view(task) for task in stored], reused=False)


def list_task_views(
    status: str | None = None, assignee: str | None = None, seat: str | None = None
) -> list[TaskView]:
    tasks = repository.list_tasks(status=status, assignee=assignee, seat=seat)
    return [to_view(task) for task in tasks]


def set_status(task_id: str, status: str) -> TaskView:
    return to_view(repository.update_task_status(task_id, status))


def add_dependencies(edges: list[tuple[str, str]]) -> list[TaskDependency]:
    return repository.add_dependencies(edges)


# --- Task records (TaskStore, uuid-backed) ----------------------------------


class TaskNotFound(Exception):
    pass


class TaskChanged(Exception):
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

    def list(
        self, *, month_code=None, semester_code=None, status=None,
        stakeholder_code=None, updated_since=None, limit=50, offset=0,
    ):
        def query(table):
            request = table.select("*", count="exact")
            if month_code is not None:
                request = request.eq("month_code", month_code)
            if semester_code is not None:
                request = request.eq("semester_code", semester_code)
            if status is not None:
                request = request.eq("status", status)
            if stakeholder_code is not None:
                request = request.contains("stakeholder_codes", [stakeholder_code])
            if updated_since is not None:
                request = request.gte("updated_at", updated_since.isoformat())
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

    def get_many(self, task_ids):
        """One bounded read to re-authorize remembered task references."""
        ids = list({str(value) for value in task_ids})
        if len(ids) > 100:
            raise ValueError("Too many remembered tasks")
        return self._execute(lambda table: table.select("*").in_("id", ids)).data if ids else []

    def update(self, task_id: UUID, changes: TaskUpdate):
        result = self._execute(
            lambda table: table.update(changes.model_dump(mode="json", exclude_unset=True)).eq(
                "id", str(task_id)
            )
        )
        if not result.data:
            raise TaskNotFound
        return result.data[0]

    def update_if_current(self, task_id: UUID, changes: TaskUpdate, updated_at: str):
        """Fence the write against edits/reassignment after the authorization read."""
        if not updated_at:
            raise StorageUnavailable("The task has no revision timestamp.")
        result = self._execute(
            lambda table: table.update(changes.model_dump(mode="json", exclude_unset=True))
            .eq("id", str(task_id)).eq("updated_at", updated_at)
        )
        if not result.data:
            raise TaskChanged
        return result.data[0]

    def delete(self, task_id: UUID):
        result = self._execute(lambda table: table.delete().eq("id", str(task_id)))
        if not result.data:
            raise TaskNotFound

    def tracker_tasks(self, spreadsheet_id: str):
        """Read the whole source, not just the API's default first page."""
        tasks, offset = [], 0
        while True:
            result = self._execute(
                lambda table, offset=offset: table.select("*").eq(
                    "source_spreadsheet_id", spreadsheet_id
                ).order("id").range(offset, offset + 499)
            )
            tasks.extend(result.data)
            if len(result.data) < 500:
                return tasks
            offset += 500

    def insert_import_task(self, task: dict):
        return self._execute(lambda table: table.insert(task)).data

    def update_import_task(self, task_id: str, expected_updated_at: str, changes: dict):
        # If another process changed the task after preview, do not overwrite it.
        return self._execute(lambda table: table.update(changes).eq(
            "id", task_id
        ).eq("updated_at", expected_updated_at)).data

    def unfinished_for_semester(self, semester_code: str):
        """All unfinished candidates, ordered by deadline before personal filtering."""
        tasks, offset = [], 0
        while True:
            page = self._execute(lambda table, offset=offset: table.select("*").eq(
                "semester_code", semester_code
            ).neq("status", "done").order(
                "due_date", nullsfirst=False
            ).order("id").range(offset, offset + 499)).data
            tasks.extend(page)
            if len(page) < 500:
                return tasks
            offset += 500

    def by_task_code(self, task_code: str, semester_code: str):
        result = self._execute(lambda table: table.select("*").eq(
            "task_code", task_code
        ).eq("semester_code", semester_code))
        return result.data[0] if len(result.data) == 1 else None


# --- Event label enrichment (Gemini) ----------------------------------------


async def suggest_event_labels(
    tasks: list[dict],
    api_key: str,
    model: str,
) -> dict[str, str]:
    """Return {task_id: label} for tasks that lack a specific event (e.g. 'Miscellaneous')."""
    import json

    from google.genai import types

    from app.services.task_assignment import gemini_client

    if not tasks:
        return {}

    items = "\n".join(
        f'{t["id"]}: {t["title"]}'
        + (f' — {t["description"][:120]}' if t.get("description") else "")
        for t in tasks[:40]
    )

    response = await gemini_client(api_key).aio.models.generate_content(
        model=model,
        contents=items,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You label tasks for a university women-in-computing club's exec board.\n"
                "For each task give a short 2–4 word label (title case) saying what kind of "
                "work it is. Examples: Social Media, Event Logistics, Budget & Finance, "
                "Internal Planning, Outreach, Sponsorship, Marketing, Tech Workshop, "
                "Member Relations, Administrative, Awards & Recognition.\n"
                "Never return 'Miscellaneous'. "
                'Return JSON array: [{"id":"<id>","label":"<label>"}, ...]'
            ),
            response_mime_type="application/json",
            response_json_schema={
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
            },
        ),
    )

    try:
        rows = json.loads(response.text or "[]")
    except (ValueError, TypeError):
        rows = []

    return {
        item["id"]: item["label"]
        for item in rows
        if isinstance(item, dict) and item.get("id") and item.get("label")
    }
