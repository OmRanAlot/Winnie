"""Recommendations propose; explicit owner selection and admin approval authorize transfers."""

import asyncio
import re

from fastapi.concurrency import run_in_threadpool
from google.genai import errors as genai_errors
from httpx import HTTPError

from app.services.help_requests import HELP_COMMAND, help_request_reply
from app.services.member_skills import load_skills, with_skills
from app.services.members import assignment_members, task_assignments
from app.services.task_matching import suggest_candidates, workload
from app.services.tasks import TaskNotFound

CHOOSE = re.compile(r"choose HELP-(\d+) ([A-Z0-9_-]+)", re.IGNORECASE)
DECIDE = re.compile(r"(approve|deny) HELP-(\d+) v(\d+)", re.IGNORECASE)
PROGRESS = re.compile(r"\b(blocked|stuck|waiting for|waiting on|need help|delayed|rescheduled|booked|submitted|sent|finished|completed)\b", re.IGNORECASE)


class HandoffTasks:
    """Limit the existing interpreter/completion service to this group's one task."""

    def __init__(self, store, task):
        self.store, self.task = store, task

    def get(self, task_id):
        if str(task_id) != str(self.task["id"]):
            raise TaskNotFound()
        return self.store.get(task_id)

    def unfinished_for_semester(self, semester):
        return [self.task] if self.task["semester_code"] == semester and self.task["status"] != "done" else []

    def by_task_code(self, code, semester):
        return self.task if self.task["task_code"] == code and self.task["semester_code"] == semester else None


def transfer_assignment(task, request, members, semester):
    """Preserve other co-owners; replace only the person who requested the transfer."""
    aliases = members.aliases(semester)
    assigned = assignment_members(task.get("assignee_text", ""), aliases)
    if assigned is None or request["requester_code"] not in assigned:
        raise ValueError("Current ownership cannot be verified.")
    codes = (assigned - {request["requester_code"]}) | {request["selected_code"]}
    names = []
    for code in sorted(codes):
        options = sorted(row["alias"] for row in aliases if row["member_code"] == code)
        if not options:
            raise ValueError("New owner needs a verified semester alias first.")
        names.append(options[0])
    replacement = "; ".join(names)
    if assignment_members(replacement, aliases) != codes:
        raise ValueError("New assignment is ambiguous.")
    return replacement


def decide_request(store, tasks, members, settings, number, revision, action, actor=None):
    raise ValueError("Use the shared Requests queue or approve/reject REQ-number after recipient acceptance.")


async def help_workflow_reply(message, members, tasks, store, settings):
    text = message.text.strip()
    choice, decision = CHOOSE.fullmatch(text), DECIDE.fullmatch(text)
    if not settings.help_workflow_enabled:
        if choice or decision or HELP_COMMAND.fullmatch(text):
            return "The help workflow isn't enabled yet. Please contact the project admin."
        return None
    if choice or decision:
        if message.conversation_type != "dm" or message.platform != "imessage" or not message.sender_id:
            return "Use a direct message from your linked account for help requests and approvals."
        member = await run_in_threadpool(members.resolve, message.platform, message.sender_id)
        if not member:
            return "Your messaging account is not linked. Text whoami for setup details."
        try:
            if decision:
                return "Use Requests or text approve/reject REQ-number after recipient acceptance. Legacy HELP approvals are disabled."
            number, selected = choice.groups()
            request = await run_in_threadpool(store.get, int(number))
            if not request or request["requester_code"] != member["code"]:
                return "I couldn't find that help request for your account."
            result = await run_in_threadpool(store.rpc, "help_transition", p_request=int(number),
                p_revision=request["revision"], p_action="select", p_actor=member["code"], p_selected=selected.upper())
            return result["reply"]
        except ValueError as exc:
            return str(exc)
    reply = await run_in_threadpool(help_request_reply, message, members, tasks, store, settings.active_semester)
    if not reply or not reply.startswith("Saved help request"):
        return reply
    request = await run_in_threadpool(store.receipt, message)
    if not request or request["status"] not in ("awaiting_recommendations", "suggestions_ready"):
        return "Your help request is already being reviewed. Ownership changes only after admin approval."
    task = await run_in_threadpool(tasks.get, request["task_id"])
    if task.get("semester_code") != settings.active_semester:
        return "That task belongs to another semester. Ask the project admin to review it."
    candidates = request["candidates"]
    if not candidates:
        if not settings.gemini_api_key:
            return f"Saved HELP-{request['request_no']}. Recommendations need Gemini configured; no ownership changed."
        all_tasks = await run_in_threadpool(tasks.unfinished_for_semester, settings.active_semester)
        aliases = await run_in_threadpool(members.aliases, settings.active_semester)
        assignments = task_assignments(all_tasks, aliases)
        current = assignments.get(str(task["id"]))
        if current is None:
            return "Assignment aliases need review before I can recommend a replacement."
        people = with_skills(await run_in_threadpool(members.list_active), load_skills())
        try:
            candidates = await asyncio.wait_for(suggest_candidates(
                task, people, current, workload(all_tasks, assignments), settings), timeout=12)
        except (TimeoutError, ValueError, HTTPError, genai_errors.APIError):
            return f"Saved HELP-{request['request_no']}, but recommendations aren't available right now. Retry help {task['task_code']}."
        await run_in_threadpool(store.rpc, "help_transition", p_request=request["request_no"],
            p_revision=request["revision"], p_action="candidates", p_actor=request["requester_code"], p_candidates=candidates)
    if not candidates:
        return f"I couldn't find a suitable replacement for {task['task_code']}. No ownership changed. Contact the admin for help."
    lines = [f"HELP-{request['request_no']}: suggested replacements for {task['task_code']}:"]
    for candidate in candidates:
        lines.append(f"{candidate['name']} ({candidate['code']}): {candidate['reason']} — {candidate['open']} open tasks.")
    lines.append(f"Reply choose HELP-{request['request_no']} MEMBER_CODE. The recipient must accept before admin approval; ownership is unchanged.")
    return "\n".join(lines)


async def group_reply(message, members, tasks, completions, interpreter, store, settings):
    """Only registered handoff groups; unrelated groups never enter task interpretation."""
    if not settings.help_workflow_enabled or message.platform != "imessage" or not message.space_id or not message.message_id:
        return None
    request = await run_in_threadpool(store.group, message.space_id)
    if not request:
        return None
    member = await run_in_threadpool(members.resolve, message.platform, message.sender_id or "")
    if not member or member["code"] not in (request["requester_code"], request["selected_code"]):
        return None
    task = await run_in_threadpool(tasks.get, request["task_id"])
    if task["updated_at"] != request["task_version"] and task["status"] != "done":
        return "The task changed since this handoff. Please contact the admin before updating it here."
    text = message.text.strip()
    if text.lower().startswith("update ") and len(text) > 7:
        await run_in_threadpool(store.rpc, "report_help_group", p_request=request["request_no"],
            p_platform=message.platform, p_message=message.message_id, p_actor=member["code"], p_summary=text[7:1500])
        return "Saved this task update for admin review."
    if member["code"] == request["selected_code"]:
        from app.services.conversation import conversation_reply
        personal = message.model_copy(update={"conversation_type": "dm"})
        reply = await run_in_threadpool(conversation_reply, personal, members, HandoffTasks(tasks, task), completions, interpreter, settings)
        from app.services.conversation import HelpIntent
        if isinstance(reply, HelpIntent):
            return f"Request replacement suggestions in a direct message: help {reply.task_code}."
        current = await run_in_threadpool(tasks.get, task["id"])
        # The database completion trigger queues one admin notification atomically.
        if current["status"] != "done" and PROGRESS.search(text):
            await run_in_threadpool(store.rpc, "report_help_group", p_request=request["request_no"],
                p_platform=message.platform, p_message=message.message_id, p_actor=member["code"], p_summary=text[:1500])
        return reply
    if PROGRESS.search(text):
        await run_in_threadpool(store.rpc, "report_help_group", p_request=request["request_no"],
            p_platform=message.platform, p_message=message.message_id, p_actor=member["code"], p_summary=text[:1500])
        return "Saved this task update for admin review."
    if text.lower().startswith("done "):
        return "Only the new owner can confirm completion."
    return None
