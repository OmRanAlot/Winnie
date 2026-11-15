"""Admin decisions require a configured key even in development; texts use verified admin identities."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_admin
from app.core.settings import Settings
from app.integrations.help_requests import HelpRequestStore
from app.integrations.supabase import StorageUnavailable
from app.routes.reminders import authorize_reminder_bridge
from app.services.help_workflow import decide_request
from app.services.members import MemberStore
from app.services.tasks import TaskStore

authorize_admin = require_admin


router = APIRouter(prefix="/api/help-requests", tags=["help-requests"], dependencies=[Depends(authorize_admin)])
internal = APIRouter(prefix="/api/internal/help", tags=["internal-help"], dependencies=[Depends(authorize_reminder_bridge)])


def get_help_store():
    return HelpRequestStore()


Store = Annotated[HelpRequestStore, Depends(get_help_store)]


class Decision(BaseModel):
    action: Literal["approve", "deny"]
    revision: int = Field(ge=1)


class NotificationResult(BaseModel):
    delivery_id: UUID
    claim_token: UUID
    outcome: Literal["sent", "uncertain"]
    provider_id: str | None = Field(default=None, max_length=500)


class GroupBinding(BaseModel):
    delivery_id: UUID
    claim_token: UUID
    group_id: str = Field(min_length=1, max_length=500)


@router.get("")
def pending_requests(store: Store):
    if not Settings().help_workflow_enabled:
        raise HTTPException(503, "Help workflow is disabled.")
    try:
        return {"success": True, "data": store.pending()}
    except StorageUnavailable:
        raise HTTPException(503, "Help request storage is unavailable.")


@router.post("/{number}/decision")
def decide(number: int, body: Decision, store: Store):
    settings = Settings()
    if not settings.help_workflow_enabled:
        raise HTTPException(503, "Help workflow is disabled.")
    try:
        reply = decide_request(store, TaskStore(), MemberStore(), settings, number, body.revision, body.action)
        return {"success": True, "data": {"reply": reply}}
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except StorageUnavailable:
        raise HTTPException(409, "Request unavailable or changed. Refresh before deciding.")


@internal.post("/next")
def next_notification(store: Store):
    settings = Settings()
    if not settings.help_workflow_enabled:
        return {"delivery": None}
    try:
        return {"delivery": store.rpc("claim_help_notification", p_groups_enabled=settings.help_groups_enabled)}
    except StorageUnavailable:
        raise HTTPException(503, "Help notification storage is unavailable.")


@internal.post("/result")
def notification_result(body: NotificationResult, store: Store):
    if body.outcome == "sent" and not body.provider_id:
        raise HTTPException(422, "A provider receipt is required.")
    try:
        return {"status": store.rpc("finish_help_notification", p_id=str(body.delivery_id),
            p_token=str(body.claim_token), p_outcome=body.outcome, p_provider_id=body.provider_id)}
    except StorageUnavailable:
        raise HTTPException(503, "Could not save the notification result.")


@internal.post("/bind-group")
def bind_group(body: GroupBinding, store: Store):
    if not Settings().help_workflow_enabled or not Settings().help_groups_enabled:
        raise HTTPException(503, "Group handoffs are disabled.")
    try:
        return {"bound": store.rpc("bind_help_group", p_id=str(body.delivery_id),
            p_token=str(body.claim_token), p_group_id=body.group_id)}
    except StorageUnavailable:
        raise HTTPException(409, "Group unavailable or handoff changed. No introduction authorized.")
