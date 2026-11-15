"""Authenticated dashboard forms and live dependency links."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import Principal, require_admin, require_member
from app.integrations.supabase import StorageUnavailable
from app.schemas.api import failure
from app.schemas.dashboard import EvaluationInput, TaskDraft
from app.services.dashboard import DashboardNotFound, DashboardStore

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_member)])


def get_dashboard_store():
    return DashboardStore()


Store = Annotated[DashboardStore, Depends(get_dashboard_store)]
Admin = Annotated[Principal, Depends(require_admin)]


def result(operation):
    try:
        return {"success": True, "data": operation(), "error": None, "meta": {}}
    except DashboardNotFound:
        return failure("Member not found.", 404)
    except StorageUnavailable:
        return failure("Dashboard storage is unavailable. Check the dashboard migration and retry.", 503)


def profile_id(principal):
    if principal.service:
        raise HTTPException(403, "Use an administrator's signed-in account for personal forms.")
    return principal.user_id


@router.get("/dependencies")
def dependencies(store: Store):
    return result(store.dependencies)


@router.patch("/members/{code}")
def edit_member(code: str, admin: Admin):
    raise HTTPException(403, "Board information is managed from the approved roster files and is read-only in the app.")


@router.get("/evaluations/{code}")
def evaluation(code: str, admin: Admin, store: Store):
    return result(lambda: store.evaluation(code))


@router.put("/evaluations/{code}")
def save_evaluation(code: str, body: EvaluationInput, admin: Admin, store: Store):
    reviewer = profile_id(admin)
    return result(lambda: store.save_evaluation(code, body.comments, reviewer))


@router.get("/draft")
def draft(admin: Admin, store: Store):
    return result(lambda: store.draft(profile_id(admin)))


@router.put("/draft")
def save_draft(body: TaskDraft, admin: Admin, store: Store):
    return result(lambda: store.save_draft(profile_id(admin), body.model_dump()))
