"""Board members for the dashboard.

    GET /api/members                       public profiles, with role-based skills
    GET /api/members/assignments           which members each task is assigned to
    GET /api/members/candidates/{task_id}  who could take over a pending task (skills + workload)

Only public profile fields are returned; contact details stay in the backend. Uses the same
access check as /api/tasks.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors
from httpx import HTTPError

from app.integrations.supabase import StorageUnavailable
from app.routes.tasks import authorize_tasks, envelope
from app.services.member_skills import load_skills, with_skills
from app.services.members import AliasConflict, MemberStore, task_assignments
from app.services.task_matching import suggest_candidates, workload
from app.services.tasks import TaskNotFound, TaskStore
from app.settings import Settings

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


def semester_tasks(tasks: TaskStore, semester: str) -> list[dict]:
    all_tasks, offset = [], 0
    while True:
        page, total = tasks.list(semester_code=semester, limit=PAGE, offset=offset)
        all_tasks.extend(page)
        offset += PAGE
        if len(page) < PAGE or offset >= (total or 0):
            return all_tasks


@router.get("")
def list_members(members: Annotated[MemberStore, Depends(get_member_store)]):
    try:
        data = with_skills(members.list_active(), load_skills())
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
        data = task_assignments(semester_tasks(tasks, semester), aliases)
    except AliasConflict:
        return failure(409, "Member aliases are ambiguous. Ask the project admin to review them.")
    except StorageUnavailable:
        return failure(503, "Member storage is unavailable. Check Supabase configuration.")
    unresolved = sum(codes is None for codes in data.values())
    return envelope(data, {"semester": semester, "tasks": len(data), "unresolved": unresolved,
                           "aliases": len(aliases)})


@router.get("/candidates/{task_id}")
async def task_candidates(
    task_id: UUID,
    members: Annotated[MemberStore, Depends(get_member_store)],
    tasks: Annotated[TaskStore, Depends(get_task_store)],
):
    """Up to 3 members whose skills fit this task, lightest workload first; never the assignee."""
    settings = Settings()
    if not settings.gemini_api_key:
        return failure(503, "Skill matching is not configured. Set GEMINI_API_KEY.")
    try:
        task = tasks.get(task_id)
        if task.get("status") == "done":
            return envelope([], {"reason": "Task is already done."})
        all_tasks = semester_tasks(tasks, settings.active_semester)
        assignments = task_assignments(all_tasks, members.aliases(settings.active_semester))
        people = with_skills(members.list_active(), load_skills())
    except TaskNotFound:
        return failure(404, "Task not found.")
    except AliasConflict:
        return failure(409, "Member aliases are ambiguous. Ask the project admin to review them.")
    except StorageUnavailable:
        return failure(503, "Member storage is unavailable. Check Supabase configuration.")
    if not any(p["skills"] for p in people):
        return failure(409, "No member skills yet. Run: uv run python -m app.services.member_skills")
    current = assignments.get(str(task_id)) or []
    try:
        data = await suggest_candidates(task, people, current, workload(all_tasks, assignments), settings)
    except (genai_errors.APIError, HTTPError):
        return failure(502, "Gemini could not be reached. Please try again.")
    except ValueError:
        return failure(502, "Gemini returned an unusable answer. Please try again.")
    return envelope(data, {"current_assignees": current, "considered": len(people) - len(current)})
