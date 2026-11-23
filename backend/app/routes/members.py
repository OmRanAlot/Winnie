"""Board members for the dashboard.

    GET /api/members                       public profiles, with role-based skills
    GET /api/members/assignments           which members each task is assigned to
    GET /api/members/candidates/{task_id}  who could take over a pending task (skills + workload)
    GET /api/members/messaging-contacts    admin: every board phone ready for iMessage
    POST /api/members/messaging-contacts/sync  admin: link identities + enroll Photon users
    GET /api/members/{code}/advisors       members who held this member's role before

The shared directory uses the same access check as /api/tasks. Roster administration
requires a signed-in administrator and is the only member endpoint with contact details.
"""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors
from httpx import HTTPError
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import Principal, require_admin
from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable
from app.routes.tasks import authorize_tasks, envelope
from app.schemas.roster import RosterCreate, RosterUpdate
from app.schemas.tasks import StakeholderCode
from app.services.member_history import advisors_for, load_previous_roles, with_previous_roles
from app.services.member_skills import load_skills, with_skills
from app.services.members import AliasConflict, MemberStore, RosterWriteError, task_assignments
from app.services.messaging_contacts import (
    MessagingContactsError,
    MessagingContactStore,
    board_phone_rows,
    sync_board_phones,
)
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


def get_messaging_contacts():
    return MessagingContactStore()


def failure(status, message):
    return JSONResponse(status_code=status, content={
        "success": False, "data": None, "error": {"message": message}, "meta": {},
    })


def require_roster_admin(actor: Annotated[Principal, Depends(require_admin)]):
    if actor.service:
        raise HTTPException(403, "Sign in as an administrator to manage the roster.")
    return actor


RosterAdmin = Annotated[Principal, Depends(require_roster_admin)]
Members = Annotated[MemberStore, Depends(get_member_store)]
ROSTER_UNAVAILABLE = "The roster is unavailable. Check that the roster migration is applied."


def save_roster_entry(code, body, response, actor, members, *, create=False):
    try:
        saved = members.save_roster_member(
            actor.user_id, code, Settings().active_semester, body.model_dump(exclude_unset=True),
            create=create,
        )
    except RosterWriteError as error:
        if error.code == "23505":
            if str(error).startswith("That name"):
                return failure(409, "That name is already used on the roster or in the task tracker.")
            return failure(409, "That email is already linked to another member.")
        if error.code == "P0002":
            return failure(404, "Member not found.")
        if error.code == "42501":
            return failure(403, "Administrator access is required.")
        if error.code == "40P01":
            return failure(409, "The roster changed during this edit. Reload it and try again.")
        if str(error).startswith(("Confirm the member", "Ask another administrator")):
            return failure(422, str(error))
        return failure(422, "Check the submitted roster fields.")
    except StorageUnavailable:
        return failure(503, ROSTER_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return envelope(saved)


@router.get("/roster")
def list_roster(response: Response, _actor: RosterAdmin, members: Members):
    try:
        data = members.list_roster()
    except StorageUnavailable:
        return failure(503, ROSTER_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return envelope(data, {"total": len(data)})


@router.post("/roster", status_code=201)
def create_roster_entry(body: RosterCreate, response: Response, actor: RosterAdmin, members: Members):
    return save_roster_entry(f"WICS_{uuid4().hex.upper()}", body, response, actor, members, create=True)


@router.patch("/roster/{code}")
def update_roster_entry(
    code: StakeholderCode, body: RosterUpdate, response: Response, actor: RosterAdmin, members: Members
):
    return save_roster_entry(code, body, response, actor, members)


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


class MessagingSyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enroll_photon: bool = True
    rotate_across_lines: bool = Field(
        default=True,
        description="On dedicated Photon projects, enroll each board phone on every line.",
    )


@router.get("/messaging-contacts")
def list_messaging_contacts(
    response: Response,
    _actor: RosterAdmin,
    members: Members,
    contacts: Annotated[MessagingContactStore, Depends(get_messaging_contacts)],
):
    """Every active, consented board phone with iMessage identity status."""
    try:
        roster = members.list_roster()
        identities = contacts.list_identities()
        data = board_phone_rows(roster, identities)
    except StorageUnavailable:
        return failure(503, ROSTER_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return envelope(data, {
        "total": len(data),
        "ready": sum(1 for row in data if row["ready"]),
        "with_phone": sum(1 for row in data if row.get("handle")),
    })


@router.post("/messaging-contacts/sync")
def sync_messaging_contacts(
    body: MessagingSyncInput,
    response: Response,
    _actor: RosterAdmin,
    members: Members,
    contacts: Annotated[MessagingContactStore, Depends(get_messaging_contacts)],
):
    """Link iMessage identities for all roster phones and enroll them in Photon."""
    try:
        roster = members.list_roster()
        data = sync_board_phones(
            roster, contacts, Settings(),
            enroll_photon=body.enroll_photon,
            rotate_across_lines=body.rotate_across_lines,
        )
    except MessagingContactsError as error:
        return failure(error.status, str(error))
    except StorageUnavailable:
        return failure(503, ROSTER_UNAVAILABLE)
    response.headers["Cache-Control"] = "private, no-store"
    return envelope(data, {
        "total": data["total"],
        "ready": data["ready"],
        "mode": data.get("mode"),
        "lines": data.get("lines") or [],
    })


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
