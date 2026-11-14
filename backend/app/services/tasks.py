"""Task persistence and filtered queries; called by routes/tasks.py."""

from collections.abc import Callable
from uuid import UUID

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client
from app.task_schemas import TaskCreate, TaskUpdate


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
