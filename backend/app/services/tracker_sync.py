"""Plan and apply a reviewed CSV import, keyed by permanent spreadsheet/task IDs."""

import hashlib
import json

from app.integrations.supabase import StorageUnavailable
from app.services.tasks import TaskStore

SHEET_FIELDS = (
    "title", "description", "status", "priority", "assignee_text", "deadline_text",
    "due_date", "event_tag", "category", "project_name", "snapshot_month",
    "source_tab_id", "source_tab_name",
)


class ImportConflict(ValueError):
    """Input or current database state prevents a safe import."""


class ImportInterrupted(Exception):
    def __init__(self, completed, attempted):
        super().__init__("Import stopped. Some requests may already have saved tasks.")
        self.completed = completed
        self.attempted = attempted


def plan_import(preview: dict, store: TaskStore, target_url: str) -> dict:
    """Database reads only. Never match by title, row number, or task-code prefix."""
    if preview["archived"]:
        raise ImportConflict("OLD tabs cannot update current tasks. Use the active snapshot.")
    if not preview["rows"]:
        raise ImportConflict("No tasks to import.")
    if preview["summary"]["rows_with_errors"]:
        raise ImportConflict("Fix all preview errors before planning an import.")
    tasks = [row["task"] for row in preview["rows"]]
    spreadsheet_ids = {task["source_spreadsheet_id"] for task in tasks}
    if len(spreadsheet_ids) != 1 or None in spreadsheet_ids:
        raise ImportConflict("An import must belong to one identified spreadsheet.")
    spreadsheet_id = tasks[0]["source_spreadsheet_id"]
    existing = store.tracker_tasks(spreadsheet_id)
    # Do not let an older month insert new tasks or overwrite a later snapshot.
    same_tracker = [task for task in existing if (
        task.get("semester_code") == preview["semester_code"]
        and task.get("project_name") == tasks[0].get("project_name")
    )]
    stored_months = [task["snapshot_month"] for task in same_tracker if task.get("snapshot_month")]
    incoming_month = preview["snapshot_month"]
    if stored_months and (not incoming_month or incoming_month < max(stored_months)):
        raise ImportConflict("A later snapshot is already stored. Do not import this older copy.")
    by_id = {}
    for task in existing:
        key = task.get("source_task_id")
        if key is not None:
            if key in by_id:
                raise ImportConflict("Duplicate stored source IDs. Check the database migration.")
            by_id[key] = task
    operations = []
    for task in sorted(tasks, key=lambda item: item["source_task_id"]):
        key = task["source_task_id"]
        old = by_id.get(key)
        if old is None:
            operations.append({"action": "insert", "source_task_id": key, "values": task})
            continue
        if old.get("semester_code") != task["semester_code"] or old.get("source") != "sheet":
            raise ImportConflict("A task ID already belongs to a different source or semester.")
        if old.get("snapshot_month") and (
            not task["snapshot_month"] or task["snapshot_month"] < old["snapshot_month"]
        ):
            raise ImportConflict("A task already has a newer snapshot.")
        changes = {
            field: task[field] for field in SHEET_FIELDS
            if task[field] != old.get(field)
            # A CSV need not know the tab gid; don't erase an existing one.
            and not (field == "source_tab_id" and task[field] is None)
        }
        operation = {
            "action": "update" if changes else "unchanged", "source_task_id": key,
            "id": old["id"], "expected_updated_at": old["updated_at"], "values": changes,
            "before": {field: old.get(field) for field in changes},
        }
        operations.append(operation)
    plan = {
        "spreadsheet_id": spreadsheet_id, "semester_code": preview["semester_code"],
        "target": target_url.rstrip("/"), "operations": operations,
        "warnings": preview["summary"]["warnings"],
        "summary": {
            action: sum(op["action"] == action for op in operations)
            for action in ("insert", "update", "unchanged")
        },
    }
    # Bind confirmation to this database, exact input, and records observed during preview.
    serialized = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    plan["plan_id"] = hashlib.sha256(serialized.encode()).hexdigest()
    return plan


def apply_import(plan: dict, store: TaskStore, expected_plan: str) -> dict:
    if plan["plan_id"] != expected_plan:
        raise ImportConflict("The plan changed. Review a fresh preview before applying.")
    completed = {"insert": 0, "update": 0, "unchanged": 0}
    attempted = 0
    for operation in plan["operations"]:
        action = operation["action"]
        if action == "unchanged":
            completed[action] += 1
            continue
        attempted += 1
        try:
            if action == "insert":
                saved = store.insert_import_task(operation["values"])
            else:
                saved = store.update_import_task(
                    operation["id"], operation["expected_updated_at"], operation["values"],
                )
            if len(saved) != 1:
                raise StorageUnavailable("Task changed during import; preview again.")
        except StorageUnavailable as exc:
            # REST calls are individual transactions. Never claim the whole batch rolled back.
            raise ImportInterrupted(completed.copy(), attempted) from exc
        completed[action] += 1
    return {"mode": "applied", "completed": completed, "write_requests": attempted}
