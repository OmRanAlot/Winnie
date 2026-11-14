"""Receive messages from the trusted Photon bridge and return a personal reply."""

from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore
from app.services.message_replies import MENU, personal_reply
from app.services.tasks import TaskStore
from app.settings import Settings

router = APIRouter(prefix="/api", tags=["messages"])


class IncomingMessage(BaseModel):
    text: str = Field(max_length=10000)
    sender_id: str | None = Field(default=None, min_length=1, max_length=500)
    platform: str | None = Field(default=None, max_length=50)
    conversation_type: Literal["dm", "group", "unknown"] = "unknown"


def get_member_store():
    return MemberStore()


def get_task_store():
    return TaskStore()


@router.post("/messages")
def handle_message(
    message: IncomingMessage,
    members: Annotated[MemberStore, Depends(get_member_store)],
    tasks: Annotated[TaskStore, Depends(get_task_store)],
    x_winnie_bridge_secret: str = Header(default=""),
):
    text = message.text.strip().lower()
    if text == "ping":
        return {"reply": "pong 🏓"}
    if text not in ("1", "tasks", "my tasks", "2", "whoami"):
        return {"reply": MENU}
    settings = Settings()
    expected = settings.messaging_bridge_secret.get_secret_value()
    if not expected:
        raise HTTPException(503, "Configure the messaging bridge secret before personal commands.")
    if not compare_digest(x_winnie_bridge_secret.encode(), expected.encode()):
        raise HTTPException(401, "Invalid messaging bridge credentials.")
    try:
        reply = personal_reply(message, members, tasks, settings.active_semester)
    except StorageUnavailable:
        reply = "I couldn't load member or task data right now. Please try again later."
    return {"reply": reply}

