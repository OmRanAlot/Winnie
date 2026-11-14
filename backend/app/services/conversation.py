"""Interpret a single message, then enforce task ownership before any status change."""

import hashlib
import json
import re

from pydantic import ValidationError

from app.agents.message_interpreter import InterpretationUnavailable, MessageDecision
from app.integrations.supabase import StorageUnavailable
from app.services.members import AliasConflict, assignment_members, normalize_sender
from app.services.message_replies import MENU, verified_personal_tasks
from app.services.tasks import TaskNotFound

BARE_UPDATE = {
    "yes", "yeah", "yep", "done", "finished", "all done", "i'm done", "i am done",
    "it's done", "it is done", "i finished it", "i've finished it", "i completed it",
}
UNCERTAIN_COMPLETION = re.compile(
    r"\b(not|never|haven't|hasn't|didn't|don't|can't|cannot|won't|almost|nearly|will|would|"
    r"could|should|might|if|when|once|planning|plan to|need to|want to|incomplete|unfinished|"
    r"my part|part of|partially|mostly|halfway)\b"
    r"|\b\w+n't\b|\?",
    re.IGNORECASE,
)
DIRECT_DONE = re.compile(r"done\s+(WIN-[0-9]{6}-[0-9]+)", re.IGNORECASE)
COMPLETION_WORD = re.compile(
    r"\b(done|finished|completed|sent|booked|submitted|ordered|uploaded|published|delivered|paid|confirmed)\b",
    re.IGNORECASE,
)


def request_hash(message):
    payload = {key: getattr(message, key) for key in (
        "text", "platform", "sender_id", "conversation_type",
    )}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def clarify(tasks):
    lines = ["Which task do you mean? Name the task/event, or text done followed by its WIN code."]
    for task in tasks[:5]:
        lines.append(f"- {task['title']} ({task['task_code']})")
    return "\n".join(lines)


def conversation_reply(message, members, tasks, completions, interpreter, settings):
    if message.conversation_type != "dm":
        return "Please text me directly to discuss your tasks."
    if message.platform != "imessage" or not message.sender_id:
        return "I could not identify the sender. Please use your registered iMessage account."
    message = message.model_copy(update={"sender_id": normalize_sender(message.sender_id)})
    member = members.resolve(message.platform, message.sender_id)
    if not member:
        return "Your messaging account is not linked yet. Text whoami for setup details."
    direct = DIRECT_DONE.fullmatch(message.text.strip())
    if not direct and not settings.message_ai_enabled:
        return MENU + "\nNatural-language replies are not enabled yet."
    if not message.message_id:
        return "Your listener needs the message-ID update. Restart messaging before updating tasks."
    digest = request_hash(message)
    cached = completions.receipt(
        message.platform, message.message_id, message.sender_id, member["code"], digest,
    )
    if cached:
        return cached
    semester = settings.active_semester
    aliases = members.aliases(semester)
    try:
        if direct:
            task = tasks.by_task_code(direct[1].upper(), semester)
            assigned = assignment_members(task.get("assignee_text", ""), aliases) if task else None
            if assigned is None or member["code"] not in assigned:
                return "I couldn't find a task assigned to you with that code in the active semester."
        else:
            selected, _ = verified_personal_tasks(
                tasks.unfinished_for_semester(semester), aliases, member["code"],
            )
            if message.text.strip().lower().rstrip(".! ") in BARE_UPDATE:
                return clarify(selected)
            if len(message.text) > 3000 or len(selected) > settings.message_ai_max_tasks:
                return clarify(selected)
            decision = MessageDecision.model_validate(interpreter.interpret(message.text, selected))
            allowed = {str(task["id"]): task for task in selected}
            if set(decision.task_ids) - allowed.keys() or len(set(decision.task_ids)) != len(decision.task_ids):
                return clarify(selected)
            if decision.intent != "complete_task":
                return decision.reply
            normalized = message.text.replace("’", "'")
            if (
                not decision.completion_asserted or len(decision.task_ids) != 1
                or decision.confidence < 0.9
                or not decision.evidence_quote.strip()
                or decision.evidence_quote not in message.text
                or UNCERTAIN_COMPLETION.search(normalized)
                or not COMPLETION_WORD.search(normalized)
            ):
                return clarify(selected)
            task = allowed[decision.task_ids[0]]
            # A generic title that occurs twice needs the event or canonical code.
            duplicates = [item for item in selected if (
                item["title"].strip().casefold() == task["title"].strip().casefold()
            )]
            explicit_code = any(code and re.search(
                r"(?<![A-Za-z0-9_-])" + re.escape(code) + r"(?![A-Za-z0-9_-])",
                message.text, re.IGNORECASE,
            ) for code in (task.get("task_code"), task.get("source_task_id")))
            if len(duplicates) > 1 and not explicit_code:
                return clarify(duplicates)
        # Recheck after the model call; a task/assignment may have changed meanwhile.
        try:
            current = tasks.get(task["id"])
        except TaskNotFound:
            return "That task is no longer available. Text tasks to refresh your list."
        if current.get("updated_at") != task.get("updated_at"):
            return "That task changed while I was reading your message. Text tasks and try again."
        fresh_aliases = members.aliases(semester)
        assigned = assignment_members(current.get("assignee_text", ""), fresh_aliases)
        if current.get("semester_code") != semester or assigned is None or member["code"] not in assigned:
            return "I couldn't verify that this task is still assigned to you. No change was made."
        try:
            result = completions.complete(message, member["code"], current, digest, semester)
        except StorageUnavailable:
            return "I couldn't confirm whether the update was saved. Text tasks to check before retrying."
        # Only the database's committed result may claim that a task was completed.
        return result["reply"]
    except AliasConflict:
        return "Member assignment setup needs review. Please contact the project admin."
    except (InterpretationUnavailable, ValidationError):
        return "I couldn't interpret that reliably. No task was changed. Try tasks or done with its WIN code."
