"""Board members for the dashboard.

    GET /api/members                       public profiles, with role-based skills
    GET /api/members/assignments           which members each task is assigned to
    GET /api/members/candidates/{task_id}  who could take over a pending task (skills + workload)
    GET /api/members/{code}/advisors       members who held this member's role before

Only public profile fields are returned; contact details stay in the backend. Uses the same
access check as /api/tasks.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors
from httpx import HTTPError

from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable
from app.routes.tasks import authorize_tasks, envelope
from app.services.member_history import advisors_for, load_previous_roles, with_previous_roles
from app.services.member_skills import load_skills, with_skills
from app.services.members import AliasConflict, MemberStore, task_assignments
from app.services.task_matching import suggest_candidates, workload
from app.services.tasks import TaskNotFound, TaskStore

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


def profiles(members: MemberStore) -> list[dict]:
    """Active members with role-based skills and previous roles attached."""
    skills = load_skills()
    return with_previous_roles(with_skills(members.list_active(), skills), load_previous_roles(),
                               members.previous_roles(), skills)


@router.get("")
def list_members(members: Annotated[MemberStore, Depends(get_member_store)]):
    try:
        data = profiles(members)
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
        # Skills from previous roles count too: a former Event Coordinator can cover event work.
        people = [{**p, "skills": list(dict.fromkeys(p["skills"] + p["previous_role_skills"]))}
                  for p in profiles(members)]
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


@router.get("/{code}/advisors")
def role_advisors(code: str, members: Annotated[MemberStore, Depends(get_member_store)]):
    """Members who previously held this member's current role, e.g. to ask for advice when stuck."""
    try:
        people = profiles(members)
    except StorageUnavailable:
        return failure(503, "Member storage is unavailable. Check Supabase configuration.")
    member = next((p for p in people if p["code"] == code), None)
    if member is None:
        return failure(404, "Member not found.")
    data = [{"code": a["code"], "display_name": a["display_name"], "board_role": a["board_role"],
             "previous_roles": a["previous_roles"]} for a in advisors_for(member, people)]
    return envelope(data, {"role": member["board_role"], "total": len(data)})
