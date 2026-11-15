"""Bind affirmative replies to one actual help check-in, and verify current ownership."""

import re

from app.services.conversation import request_hash
from app.services.members import AliasConflict, assignment_members, normalize_sender
from app.services.reminders import utc_now
from app.services.tasks import TaskNotFound

HELP_COMMAND = re.compile(r"(?:help|need help)\s+(WIN-[0-9]{6}-[0-9]+)", re.IGNORECASE)
YES = {"yes", "yes please", "yeah", "yea", "yep", "sure", "i need help", "i could use help",
       "yes i need help", "yeah i need help", "yea i need help", "yes i'd like suggestions"}
NO = {"no", "no thanks", "not now"}


def help_request_reply(message, members, tasks, store, semester, clock=utc_now):
    text = message.text.strip().lower().replace(",", "").rstrip(".! ")
    command = HELP_COMMAND.fullmatch(text)
    if not command and text not in YES | NO:
        return None
    if message.conversation_type != "dm" or message.platform != "imessage" or not message.sender_id:
        return "Please ask for help in a direct message from your linked account."
    message = message.model_copy(update={"sender_id": normalize_sender(message.sender_id)})
    member = members.resolve(message.platform, message.sender_id)
    if not member:
        return "Your messaging account is not linked yet. Text whoami for setup details."
    if not message.message_id:
        return "Restart the updated listener before making a help request."
    aliases = members.aliases(semester)

    def authorized(task):
        if not task or task.get("semester_code") != semester or task["status"] == "done":
            return False
        assigned = ({task["owner_code"]} if task.get("owner_code") else assignment_members(task.get("assignee_text", ""), aliases))
        return assigned is not None and member["code"] in assigned

    try:
        if command:
            task = tasks.by_task_code(command[1].upper(), semester)
            if not authorized(task):
                return "I couldn't find an unfinished task assigned to you with that code."
        else:
            offers = store.recent_offers(member["code"], message.sender_id, clock())
            candidates = {}
            for offer in offers:
                try:
                    candidate = tasks.get(offer["task_id"])
                except TaskNotFound:
                    continue
                if authorized(candidate) and candidate.get("due_date") == offer["due_date"]:
                    candidates[candidate["id"]] = candidate
            if not candidates:
                return None
            if text in NO:
                return "Okay, no help request was made. You can ask later with help followed by the task's WIN code."
            if len(candidates) != 1:
                lines = ["Which check-in are you replying to? Send help followed by its WIN code:"]
                lines.extend(f"- {task['title']} ({task['task_code']})" for task in candidates.values())
                return "\n".join(lines)
            task = next(iter(candidates.values()))
        return store.request(message, member["code"], task, request_hash(message), semester)["reply"]
    except AliasConflict:
        return "Member assignment setup needs review. Please contact the project admin."
