"""Receive messages from the trusted Photon bridge and return a personal reply."""

from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.agents.message_interpreter import GeminiMessageInterpreter
from app.core.settings import Settings
from app.integrations.conversation_memory import ConversationMemoryStore
from app.integrations.help_requests import HelpRequestStore
from app.integrations.message_completion import CompletionStore
from app.integrations.supabase import StorageUnavailable
from app.services.conversation import HelpIntent, conversation_reply
from app.services.conversation_memory import FORGET, prepare_context
from app.services.help_requests import HELP_COMMAND
from app.services.help_workflow import group_reply, help_workflow_reply
from app.services.members import AliasConflict, MemberStore
from app.services.message_replies import MENU, personal_reply, verified_personal_tasks
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


def get_memory_store():
    return ConversationMemoryStore()


@router.post("/messages")
async def handle_message(
    message: IncomingMessage,
    members: Annotated[MemberStore, Depends(get_member_store)],
    tasks: Annotated[TaskStore, Depends(get_task_store)],
    completions: Annotated[CompletionStore, Depends(get_completion_store)],
    interpreter: Annotated[GeminiMessageInterpreter, Depends(get_message_interpreter)],
    help_requests: Annotated[HelpRequestStore, Depends(get_help_request_store)],
    reassignments: Annotated[MessagingReassignmentStore, Depends(get_reassignment_store)],
    memory_store: Annotated[ConversationMemoryStore, Depends(get_memory_store)],
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
    return await process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, settings, memory_store)


async def process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, settings, memory_store=None):
    """Shared business logic; callers must first verify bridge credentials or a Photon signature."""
    if message.conversation_type == 'dm' and message.text.strip().lower() == 'ping':
        return {'reply': 'pong 🏓'}  # Health checks must not create/evict conversation turns.
    context, memory_failed = None, False
    if message.conversation_type == 'dm' and getattr(settings, 'message_memory_enabled', False):
        try:
            context = await run_in_threadpool(prepare_context, message, members, tasks, settings,
                memory_store if memory_store is not None else ConversationMemoryStore())
        except (StorageUnavailable, AliasConflict, ValueError):
            memory_failed = True
    if message.conversation_type == 'dm' and message.text.strip().lower() in FORGET:
        if context is None:
            return {'reply': 'Conversation memory could not be cleared. Check your linked account and memory configuration.'}
        try:
            await run_in_threadpool(context.clear)
            return {'reply': 'Forgot this conversation. Task records and pending requests are unchanged.'}
        except StorageUnavailable:
            return {'reply': 'Conversation memory could not be cleared. Please try again.'}
    if context is not None:
        cached = context.replay(message)
        if cached is not None:
            return {'reply': cached}
    result = await _process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, settings, context)
    if context is not None and isinstance(result.get('reply'), str):
        try:
            await run_in_threadpool(context.record, message, result['reply'])
        except (StorageUnavailable, ValueError, TypeError):
            memory_failed = True
    if memory_failed and isinstance(result.get('reply'), str):
        result['reply'] += '\nConversation memory is unavailable; include the task name/code in your next message.'
    return result


async def _process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, settings, context=None):
    text = message.text.strip().lower()
    if text == "ping" and message.conversation_type != "group":
        return {"reply": "pong 🏓"}
    if text in ("", "help", "menu", "start") and message.conversation_type != "group":
        return {"reply": MENU}
    try:
        if context is not None and context.pending_help_no:
            pending = await run_in_threadpool(help_requests.get, context.pending_help_no)
            chosen = context.helper_choice(message.text, pending)
            if chosen:
                reply = await help_workflow_reply(message.model_copy(update={
                    'text': f'choose HELP-{context.pending_help_no} {chosen}',
                }), members, tasks, help_requests, settings)
                if reply and reply.startswith(('Saved REQ-', 'Already saved as REQ-')):
                    context.reset_question()
                return {'reply': reply}
        if message.conversation_type == "group":
            reply = await group_reply(message, members, tasks, completions, interpreter, help_requests, settings)
            return {"reply": reply}
        elif text in ("1", "tasks", "my tasks", "2", "whoami") and not (context is not None and context.awaiting_answer and text in ('1', '2')):
            reply = await run_in_threadpool(personal_reply, message, members, tasks, settings.active_semester)
            if context is not None and text in ('1', 'tasks', 'my tasks'):
                candidates = await run_in_threadpool(tasks.unfinished_for_semester, settings.active_semester)
                aliases = await run_in_threadpool(members.aliases, settings.active_semester)
                selected, _ = verified_personal_tasks(candidates, aliases, context.member)
                context.prompt_tasks(selected[:5])
                context.focus([selected[0]['id']] if len(selected) == 1 else [])
        else:
            reply = await reassignment_reply(message, members, tasks, reassignments, settings)
            if reply is not None and context is not None:
                context.focus([])  # REQ actions always require their explicit request number.
            if reply is None and not (context is not None and context.awaiting_answer and not HELP_COMMAND.fullmatch(message.text.strip())):
                reply = await help_workflow_reply(message, members, tasks, help_requests, settings)
                command = HELP_COMMAND.fullmatch(message.text.strip())
                if context is not None and command and reply and reply.startswith(('HELP-', 'Saved HELP-', 'Saved help request')):
                    task = await run_in_threadpool(tasks.by_task_code, command[1].upper(), settings.active_semester)
                    if task:
                        context.focus([task['id']])
            if reply is None:
                reply = await run_in_threadpool(conversation_reply, message, members, tasks, completions, interpreter, settings, context)
                if isinstance(reply, HelpIntent):
                    if settings.help_workflow_enabled:
                        reply = await help_workflow_reply(message.model_copy(update={
                            "text": f"help {reply.task_code}",
                        }), members, tasks, help_requests, settings)
                    else:
                        reply = "The reassignment workflow is disabled. Contact the project admin."
            if context is not None and reply and reply.startswith('HELP-'):
                offered = await run_in_threadpool(help_requests.receipt, message)
                if offered:
                    context.offer_helpers(offered)
    except StorageUnavailable:
        reply = "I couldn't load member or task data right now. Please try again later."
    except AliasConflict:
        reply = "Member aliases need admin review before this task can be changed."
    except ValueError:
        reply = "That request changed or could not be verified. Text requests or tasks to refresh before trying again."
    return {"reply": reply}

