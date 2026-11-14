"""Receive messages from the trusted Photon bridge and return a personal reply."""

from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.message_interpreter import GeminiMessageInterpreter
from app.integrations.message_completion import CompletionStore
from app.integrations.help_requests import HelpRequestStore
from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable
from app.services.conversation import conversation_reply
from app.services.help_requests import help_request_reply
from app.services.members import MemberStore
from app.services.message_replies import MENU, personal_reply
from app.services.tasks import TaskStore

router = APIRouter(prefix="/api", tags=["messages"])


class IncomingMessage(BaseModel):
    text: str = Field(max_length=10000)
    sender_id: str | None = Field(default=None, min_length=1, max_length=500)
    platform: str | None = Field(default=None, max_length=50)
    conversation_type: Literal["dm", "group", "unknown"] = "unknown"
    message_id: str | None = Field(default=None, min_length=1, max_length=500)


def get_member_store():
    return MemberStore()


def get_task_store():
    return TaskStore()


def get_completion_store():
    return CompletionStore()


def get_message_interpreter():
    return GeminiMessageInterpreter(Settings())


def get_help_request_store():
    return HelpRequestStore()


@router.post("/messages")
def handle_message(
    message: IncomingMessage,
    members: Annotated[MemberStore, Depends(get_member_store)],
    tasks: Annotated[TaskStore, Depends(get_task_store)],
    completions: Annotated[CompletionStore, Depends(get_completion_store)],
    interpreter: Annotated[GeminiMessageInterpreter, Depends(get_message_interpreter)],
    help_requests: Annotated[HelpRequestStore, Depends(get_help_request_store)],
    x_winnie_bridge_secret: str = Header(default=""),
):
    text = message.text.strip().lower()
    if text == "ping":
        return {"reply": "pong 🏓"}
    if text in ("", "help", "menu", "start"):
        return {"reply": MENU}
    settings = Settings()
    expected = settings.messaging_bridge_secret.get_secret_value()
    if not expected:
        raise HTTPException(503, "Configure the messaging bridge secret before personal commands.")
    if not compare_digest(x_winnie_bridge_secret.encode(), expected.encode()):
        raise HTTPException(401, "Invalid messaging bridge credentials.")
    try:
        if text in ("1", "tasks", "my tasks", "2", "whoami"):
            reply = personal_reply(message, members, tasks, settings.active_semester)
        else:
            reply = help_request_reply(message, members, tasks, help_requests, settings.active_semester)
            if reply is None:
                reply = conversation_reply(message, members, tasks, completions, interpreter, settings)
    except StorageUnavailable:
        reply = "I couldn't load member or task data right now. Please try again later."
    return {"reply": reply}

