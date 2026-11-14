"""Trusted listener polls for one authorized delivery; browsers cannot send arbitrary texts."""

from secrets import compare_digest
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.settings import Settings
from app.integrations.reminders import ReminderStore
from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore
from app.services.reminders import next_reminder, utc_now
from app.services.tasks import TaskStore


def authorize_reminder_bridge(x_winnie_bridge_secret: str = Header(default="")):
    expected = Settings().messaging_bridge_secret.get_secret_value()
    if not expected:
        raise HTTPException(401, "Invalid messaging bridge credentials.")
    if not compare_digest(expected.encode(), x_winnie_bridge_secret.encode()):
        raise HTTPException(401, "Invalid messaging bridge credentials.")


router = APIRouter(prefix="/api/internal/reminders", tags=["internal-reminders"],
                   dependencies=[Depends(authorize_reminder_bridge)])


class NextRequest(BaseModel):
    scan: bool = True


class DeliveryResult(BaseModel):
    delivery_id: UUID
    claim_token: UUID
    outcome: Literal["sent", "uncertain"]
    provider_message_id: str | None = Field(default=None, max_length=500)


def get_reminder_store():
    return ReminderStore()


Store = Annotated[ReminderStore, Depends(get_reminder_store)]


@router.post("/next")
def next_delivery(request: NextRequest, store: Store):
    try:
        return next_reminder(store, TaskStore(), MemberStore(), Settings(), scan=request.scan)
    except (StorageUnavailable, ValueError, KeyError):
        raise HTTPException(503, "Reminder storage is unavailable. Check migration and settings.")


@router.post("/result")
def delivery_result(result: DeliveryResult, store: Store):
    if result.outcome == "sent" and not result.provider_message_id:
        raise HTTPException(422, "A sent result requires the provider message ID.")
    try:
        status = store.finish(str(result.delivery_id), str(result.claim_token), result.outcome,
                              result.provider_message_id, utc_now())
    except StorageUnavailable:
        raise HTTPException(503, "Could not record the delivery result.")
    return {"status": status}
