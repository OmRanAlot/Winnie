"""Chat with Winnie in the terminal: the real Gemini prompt and conversation rules, fake data.

    uv run python -m app.cli.chat_sim             # type messages; /help lists commands
    uv run python -m app.cli.chat_sim --verbose   # also show the history Gemini receives

Everything Winnie reads or writes here lives in memory: a few made-up tasks and one made-up
member. Only the made-up task text and what you type are sent to Gemini (GEMINI_API_KEY from
backend/.env). Nothing touches Supabase or Photon, and no one receives a text. Conversation
memory follows the same limits and task checks as the webhook worker. Use /tasks to list the
made-up tasks.
"""

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError

from app.agents.message_interpreter import GeminiMessageInterpreter
from app.agents.message_wording import reword
from app.core.settings import Settings
from app.routes.messages import IncomingMessage
from app.services.conversation import HelpIntent, conversation_reply
from app.services.conversation_memory import prepare_context
from app.services.messaging_reassignments import reassignment_reply

SENDER = "+15555550123"
ALIASES = [
    {"alias": "Demo One", "member_code": "ONE"},
    {"alias": "Demo Two", "member_code": "TWO"},
]
COMMANDS = (
    "Commands: /tasks  your made-up tasks | /requests  made-up reassignment requests | "
    "/history  what Gemini would be shown now | /notify  show a notice reworded | "
    "/reset  forget the conversation | /quit"
)
SEED_REQUEST = {
    "request_no": 8, "task_code": "WIN-202610-4", "title": "Order lunch for judges",
    "incoming": True, "admin_decision": "approved", "recipient_decision": "pending",
    "can_review": False, "can_respond": True, "requester_name": "Demo Two",
    "recipient_name": "Demo One",
}
SAMPLE_NOTICE = (
    'Winnie REQ-8: an admin approved offering you "Order lunch for judges" (WIN-202610-4), due 2026-11-22. '
    "Open Requests to Accept/Deny, or text accept REQ-8 / deny REQ-8. "
    "Ownership changes only if you accept."
)
SEED_TASKS = (
    ("t1", "Book room for workshop", "Workshop", "2026-11-20", "Demo One"),
    ("t2", "Email sponsor about swag", "GirlHacks", "2026-11-25", "Demo One"),
    ("t3", "Design workshop flyer", "Workshop", "2026-11-22", "Demo One"),
    ("t4", "Order lunch for judges", "GirlHacks", "2026-11-28", "Demo Two"),
)


class SimMembers:
    def resolve(self, platform, sender_id):
        if sender_id == SENDER:
            return {"code": "ONE", "display_name": "Demo One"}
        return None

    def aliases(self, semester):
        return deepcopy(ALIASES)


class SimTasks:
    def __init__(self):
        self.rows = {
            task_id: {
                "id": task_id,
                "task_code": f"WIN-202610-{number}",
                "source_task_id": f"SIM-00{number}",
                "title": title,
                "event_tag": event,
                "due_date": due,
                "assignee_text": assignee,
                "status": "todo",
                "semester_code": "fall-2026",
                "updated_at": "version-1",
            }
            for number, (task_id, title, event, due, assignee) in enumerate(SEED_TASKS, 1)
        }

    def unfinished_for_semester(self, semester):
        return deepcopy([row for row in self.rows.values() if row["status"] != "done"])

    def get(self, task_id):
        return deepcopy(self.rows[task_id])

    def by_task_code(self, code, semester):
        return next((deepcopy(row) for row in self.rows.values() if row["task_code"] == code), None)

    def mine(self):
        return [row for row in self.rows.values() if row["assignee_text"] == "Demo One"]


class SimCompletions:
    def __init__(self, tasks):
        self.tasks, self.receipts = tasks, {}

    def receipt(self, platform, event_id, sender, member, digest):
        cached = self.receipts.get(event_id)
        return cached[1] if cached and cached[0] == digest else None

    def complete(self, message, member, task, digest, semester):
        self.tasks.rows[task["id"]]["status"] = "done"
        reply = f"Marked {task['task_code']} done."
        self.receipts[message.message_id] = (digest, reply)
        return {"reply": reply, "changed": True}


class SimRequests:
    """One made-up request proposing that Demo One take over Demo Two's task."""

    def __init__(self, tasks):
        self.rows = [dict(SEED_REQUEST)]
        self.tasks = tasks

    def pending(self, _message):
        return {"can_review": False, "requests": deepcopy(self.rows)}

    def describe(self):
        if not self.rows:
            return ["  (no pending requests)"]
        return [
            f"  REQ-{row['request_no']}: {row['title']} ({row['task_code']}) - "
            "awaiting your consent"
            for row in self.rows
        ]

    def act(self, _message, action, payload):
        row = next((row for row in self.rows if row["request_no"] == payload.get("request_no")), None)
        if row is None or not row["can_respond"] or action not in ("accepted", "denied"):
            raise ValueError("No matching transfer is awaiting your consent.")
        self.rows.remove(row)
        if action == "accepted":
            task = self.tasks.rows["t4"]
            task.update(owner_code="ONE", assignee_text="Demo One", updated_at=datetime.now(UTC).isoformat())
        return {**row, "status": "approved" if action == "accepted" else "declined"}


class SimMemoryStore:
    """Keep the production conversation checkpoint in memory for this CLI session."""

    def __init__(self):
        self.row = None

    def load(self, _member, _thread):
        return self.row

    def save(self, _member, _thread, version, state, ttl):
        self.row = {
            "version": version + 1, "state": state,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
        }
        return self.row


def handle_command(line, tasks, memory, requests, reworder, write):
    if line == "/tasks":
        for row in tasks.mine():
            write(f"  {row['title']} ({row['task_code']}) due {row['due_date']} [{row['status']}]")
    elif line == "/requests":
        for text in requests.describe():
            write(text)
    elif line == "/notify":
        write(f"template: {SAMPLE_NOTICE}")
        write(f"reworded: {reworder(SAMPLE_NOTICE) if reworder else '(rewording unavailable)'}")
    elif line == "/history":
        write(json.dumps(memory.history if memory else [], indent=2))
    elif line == "/reset":
        if memory:
            memory.clear()
        write("(conversation forgotten)")
    else:
        write(f"Unknown command. {COMMANDS}")


def run(
    read: Callable[[str], str],
    write: Callable[[str], None],
    interpreter,
    settings,
    *,
    verbose: bool = False,
    reworder: Callable[[str], str] | None = None,
) -> int:
    members, tasks, store = SimMembers(), SimTasks(), SimMemoryStore()
    requests = SimRequests(tasks)
    completions = SimCompletions(tasks)
    write("Winnie simulator: made-up data, real Gemini. You are Demo One.")
    write(COMMANDS)
    while True:
        try:
            line = read("you> ").strip()
        except (EOFError, KeyboardInterrupt, StopIteration):
            break
        if line == "/quit":
            break
        if not line:
            continue
        try:
            message = IncomingMessage(
                text=line,
                sender_id=SENDER,
                platform="imessage",
                conversation_type="dm",
                message_id=f"sim-{uuid4().hex[:8]}",
            )
        except ValidationError:
            write("That message is too long for the simulator.")
            continue
        memory = prepare_context(message, members, tasks, settings, store)
        if line.startswith("/"):
            handle_command(line, tasks, memory, requests, reworder, write)
            continue
        if verbose:
            write(f"  [history sent to Gemini] {json.dumps(memory.history if memory else [])}")
        reply = asyncio.run(reassignment_reply(message, members, tasks, requests, settings, interpreter, memory))
        if reply is None:
            reply = conversation_reply(message, members, tasks, completions, interpreter, settings, memory)
        if isinstance(reply, HelpIntent):
            reply = f"[simulated] I would open a reassignment request for {reply.task_code}."
        write(f"winnie> {reply}")
        if memory:
            memory.record(message, reply)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="show the history sent to Gemini")
    args = parser.parse_args(argv)
    settings = Settings(message_ai_enabled=True, help_workflow_enabled=True, message_reword_enabled=True)
    if not settings.gemini_api_key:
        print("Set GEMINI_API_KEY in backend/.env first.")
        return 1
    return run(
        input, print, GeminiMessageInterpreter(settings), settings, verbose=args.verbose,
        reworder=lambda text: reword(text, settings),
    )


if __name__ == "__main__":
    raise SystemExit(main())
