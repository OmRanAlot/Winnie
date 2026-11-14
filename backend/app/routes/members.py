"""Board members for the dashboard: GET /api/members and GET /api/members/assignments.

Only public profile fields are returned (name, role, description, skills); contact details stay
in the backend. Uses the same access check as /api/tasks.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable
from app.routes.tasks import authorize_tasks, envelope
from app.services.members import AliasConflict, MemberStore, task_assignments
from app.services.tasks import TaskStore

router = APIRouter(
    prefix="/api/members", tags=["members"], dependencies=[Depends(authorize_tasks)]
)
PAGE = 100


def get_member_store():
    return MemberStore()


def get_task_store():
    return TaskStore()


def failure(status, message):
    return JSONResponse(status_code=status, content={
        "success": False, "data": None, "error": {"message": message}, "meta": {},
    })


@router.get("")
def list_members(members: Annotated[MemberStore, Depends(get_member_store)]):
    try:
        data = members.list_active()
    except StorageUnavailable:
        return failure(503, "Member storage is unavailable. Check Supabase configuration.")
    return envelope(data, {"total": len(data)})


@router.get("/assignments")
def list_assignments(
    members: Annotated[MemberStore, Depends(get_member_store)],
    tasks: Annotated[TaskStore, Depends(get_task_store)],
):
    """Which members each task in the active semester is assigned to, from verified aliases."""
    semester = Settings().active_semester
    try:
        aliases = members.aliases(semester)
        all_tasks, offset = [], 0
        while True:
            page, total = tasks.list(semester_code=semester, limit=PAGE, offset=offset)
            all_tasks.extend(page)
            offset += PAGE
            if len(page) < PAGE or offset >= (total or 0):
                break
        data = task_assignments(all_tasks, aliases)
    except AliasConflict:
        return failure(409, "Member aliases are ambiguous. Ask the project admin to review them.")
    except StorageUnavailable:
        return failure(503, "Member storage is unavailable. Check Supabase configuration.")
    unresolved = sum(codes is None for codes in data.values())
    return envelope(data, {"semester": semester, "tasks": len(data), "unresolved": unresolved,
                           "aliases": len(aliases)})
