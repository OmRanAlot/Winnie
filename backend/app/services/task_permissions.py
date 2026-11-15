"""Shared HTTP task-edit policy; imports and approved SQL handoffs have separate paths."""

from fastapi import HTTPException

from app.core.settings import Settings
from app.services.members import AliasConflict, assignment_members

ASSIGNMENT_FIELDS = {"owner_code", "assignee_text"}
MEMBER_FIELDS = {"status", "notes"}


def update_authorized(task_id, changes, principal, store, members):
    fields = changes.model_fields_set
    if fields & ASSIGNMENT_FIELDS:
        raise HTTPException(403, "Use a reassignment request to change task ownership.")
    if not principal.is_admin and fields - MEMBER_FIELDS:
        raise HTTPException(403, "Members may update only task status and notes.")
    task = store.get(task_id)
    if not principal.is_admin:
        code = principal.profile.get("member_code")
        assigned = set()
        if task.get("owner_code"):
            assigned = {task["owner_code"]}
        elif task.get("assignee_text"):
            try:
                assigned = assignment_members(
                    task["assignee_text"], members.aliases(Settings().active_semester),
                )
            except AliasConflict:
                assigned = None
        if (not code or not assigned or code not in assigned
                or task.get("semester_code") != Settings().active_semester):
            raise HTTPException(403, "You may update only tasks assigned to you in the active semester.")
    return store.update_if_current(task_id, changes, task.get("updated_at"))
