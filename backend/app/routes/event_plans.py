"""Administrator event proposals and exact-revision review/activation."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import Principal, require_admin
from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable
from app.schemas.api import failure
from app.schemas.event_plans import EventPlanInput, EventPlanReview, EventPlanUpdate
from app.services.event_plans import EventPlanStore

router = APIRouter(prefix="/api/event-plans", tags=["event-plans"])
Admin = Annotated[Principal, Depends(require_admin)]


def get_event_plan_store():
    return EventPlanStore()


Store = Annotated[EventPlanStore, Depends(get_event_plan_store)]


def run(store, admin, action, plan_id=None, revision=None, payload=None):
    if admin.service:
        raise HTTPException(403, "Use a signed-in administrator account to manage event plans.")
    try:
        data = store.call(admin.user_id, action, plan_id, revision, payload)
        return {"success": True, "data": data, "error": None, "meta": {}}
    except StorageUnavailable:
        return failure("Event plan storage is unavailable. Apply the event-plan migration and retry.", 503)


@router.get("")
def list_plans(admin: Admin, store: Store):
    return run(store, admin, "list")


@router.get("/{plan_id}")
def get_plan(plan_id: UUID, admin: Admin, store: Store):
    return run(store, admin, "get", plan_id)


@router.post("", status_code=201)
def create_plan(body: EventPlanInput, admin: Admin, store: Store):
    payload = body.model_dump(mode="json")
    payload["semester_code"] = Settings().active_semester
    return run(store, admin, "create", payload=payload)


@router.put("/{plan_id}")
def update_plan(plan_id: UUID, body: EventPlanUpdate, admin: Admin, store: Store):
    return run(store, admin, "update", plan_id, body.expected_revision,
               body.model_dump(mode="json", exclude={"expected_revision"}))


@router.post("/{plan_id}/review")
def review_plan(plan_id: UUID, body: EventPlanReview, admin: Admin, store: Store):
    return run(store, admin, body.decision, plan_id, body.expected_revision, {"note": body.note})
