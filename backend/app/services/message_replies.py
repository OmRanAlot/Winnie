"""Personal task replies for authenticated direct messages; no identity self-enrollment."""

from app.services.members import AliasConflict, assignment_members, normalize_sender

MENU = (
    "Hi! I am Winnie. Choose an option:\n"
    "1. Show my five earliest-due unfinished tasks\n"
    "2. Check who I am linked to\n"
    "You can also text tasks, whoami, requests, ping, describe a task you finished, "
    "or ask for replacement suggestions with help followed by its WIN code."
)


def verified_personal_tasks(candidates, aliases, member_code):
    selected, unresolved = [], False
    for task in candidates:
        assigned = ({task["owner_code"]} if task.get("owner_code")
                    else assignment_members(task.get("assignee_text", ""), aliases))
        if assigned is None:
            unresolved = True
        elif member_code in assigned:
            selected.append(task)
    selected.sort(key=lambda task: (
        task.get("due_date") is None, task.get("due_date") or "", str(task.get("id", "")),
    ))
    return selected, unresolved


def personal_reply(message, members, tasks, semester_code: str) -> str:
    command = message.text.strip().lower()
    if message.conversation_type != "dm":
        return "Please text me in a direct conversation to view your identity or personal tasks."
    if message.platform != "imessage" or not message.sender_id:
        return "I could not identify the sender. Please use your registered iMessage account."
    member = members.resolve(message.platform, message.sender_id)
    if command in ("2", "whoami"):
        if member:
            return f"You are linked to {member['display_name']} ({member['code']})."
        return (
            "Your messaging account is not linked to a member yet. Ask the project admin to link:\n"
            f"Platform: {message.platform}\nSender ID: {normalize_sender(message.sender_id)}"
        )
    if not member:
        return "Your messaging account is not linked yet. Text whoami for setup details."
    aliases = members.aliases(semester_code)
    try:
        selected, unresolved = verified_personal_tasks(
            tasks.unfinished_for_semester(semester_code), aliases, member["code"],
        )
    except AliasConflict:
        return "Member assignment setup needs review. Please contact the project admin."

    if not selected:
        reply = f"No unfinished tasks matched your verified assignments for {semester_code}."
    else:
        lines = [f"{member['display_name']}, your earliest-due unfinished tasks ({semester_code}):"]
        for number, task in enumerate(selected[:5], 1):
            deadline = task.get("due_date") or "No fixed deadline"
            title = " ".join(task["title"].split())
            if len(title) > 160:
                title = title[:157] + "..."
            status = task["status"].replace("_", " ")
            code = f" ({task['task_code']})" if task.get("task_code") else ""
            lines.append(f"{number}. {title} - {deadline} [{status}]{code}")
        reply = "\n".join(lines)
    if unresolved:
        reply += "\nSome tracker assignments still need member mapping; this list may be incomplete."
    return reply
