"""Receive messages from the trusted Photon bridge and return a personal reply."""

from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.agents.message_interpreter import GeminiMessageInterpreter
from app.core.settings import Settings
from app.integrations.help_requests import HelpRequestStore
from app.integrations.message_completion import CompletionStore
from app.integrations.supabase import StorageUnavailable
from app.services.conversation import HelpIntent, conversation_reply
from app.services.help_workflow import group_reply, help_workflow_reply
from app.services.members import AliasConflict, MemberStore
from app.services.message_replies import MENU, personal_reply
from app.services.messaging_reassignments import MessagingReassignmentStore, reassignment_reply
from app.services.tasks import TaskStore

router = APIRouter(prefix="/api", tags=["messages"])


class IncomingMessage(BaseModel):
    text: str = Field(max_length=10000)
    sender_id: str | None = Field(default=None, min_length=1, max_length=500)
    platform: str | None = Field(default=None, max_length=50)
    conversation_type: Literal["dm", "group", "unknown"] = "unknown"
    message_id: str | None = Field(default=None, min_length=1, max_length=500)
    space_id: str | None = Field(default=None, min_length=1, max_length=500)


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


def get_reassignment_store():
    return MessagingReassignmentStore()


@router.post("/messages")
async def handle_message(
    message: IncomingMessage,
    members: Annotated[MemberStore, Depends(get_member_store)],
    tasks: Annotated[TaskStore, Depends(get_task_store)],
    completions: Annotated[CompletionStore, Depends(get_completion_store)],
    interpreter: Annotated[GeminiMessageInterpreter, Depends(get_message_interpreter)],
    help_requests: Annotated[HelpRequestStore, Depends(get_help_request_store)],
    reassignments: Annotated[MessagingReassignmentStore, Depends(get_reassignment_store)],
    x_winnie_bridge_secret: str = Header(default=""),
):
    settings = Settings()
    if settings.photon_enabled:
        # The signed webhook owns incoming messages in production. Old laptop
        # listeners may still receive them; null tells those clients not to reply.
        return {"reply": None}
    text = message.text.strip().lower()
    if text == "ping" and message.conversation_type != "group":
        return {"reply": "pong 🏓"}
    if text in ("", "help", "menu", "start") and message.conversation_type != "group":
        return {"reply": MENU}
    expected = settings.messaging_bridge_secret.get_secret_value()
    if not expected:
        raise HTTPException(503, "Configure the messaging bridge secret before personal commands.")
    if not compare_digest(x_winnie_bridge_secret.encode(), expected.encode()):
        raise HTTPException(401, "Invalid messaging bridge credentials.")
    return await process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, settings)


async def process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, settings):
    """Shared business logic; callers must first verify bridge credentials or a Photon signature."""
    text = message.text.strip().lower()
    if text == "ping" and message.conversation_type != "group":
        return {"reply": "pong 🏓"}
    if text in ("", "help", "menu", "start") and message.conversation_type != "group":
        return {"reply": MENU}
    try:
        if message.conversation_type == "group":
            reply = await group_reply(message, members, tasks, completions, interpreter, help_requests, settings)
            return {"reply": reply}
        elif text in ("1", "tasks", "my tasks", "2", "whoami"):
            reply = await run_in_threadpool(personal_reply, message, members, tasks, settings.active_semester)
        else:
            reply = await reassignment_reply(message, members, tasks, reassignments, settings)
            if reply is None:
                reply = await help_workflow_reply(message, members, tasks, help_requests, settings)
            if reply is None:
                reply = await run_in_threadpool(conversation_reply, message, members, tasks, completions, interpreter, settings)
                if isinstance(reply, HelpIntent):
                    if settings.help_workflow_enabled:
                        reply = await help_workflow_reply(message.model_copy(update={
                            "text": f"help {reply.task_code}",
                        }), members, tasks, help_requests, settings)
                    else:
                        reply = "The reassignment workflow is disabled. Contact the project admin."
    except StorageUnavailable:
        reply = "I couldn't load member or task data right now. Please try again later."
    except AliasConflict:
        reply = "Member aliases need admin review before this task can be changed."
    except ValueError:
        reply = "That request changed or could not be verified. Text requests or tasks to refresh before trying again."
    return {"reply": reply}

