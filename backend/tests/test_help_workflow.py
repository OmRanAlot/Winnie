"""Fictional identities/tasks; no Gemini, Supabase or Photon network calls."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.messages import IncomingMessage
from app.services.help_requests import help_request_reply
from app.services.help_workflow import (
    HandoffTasks,
    group_reply,
    help_workflow_reply,
    transfer_assignment,
)
from app.services.tasks import TaskNotFound

TASK = {
    "id": "11111111-1111-4111-8111-111111111111", "task_code": "WIN-202610-1",
    "title": "Book room", "due_date": "2026-11-20", "status": "todo",
    "semester_code": "fall-2026", "updated_at": "version-1", "assignee_text": "Demo One",
}
ALIASES = [{"alias": "Demo One", "member_code": "ONE"},
           {"alias": "Demo Two", "member_code": "TWO"},
           {"alias": "Demo Three", "member_code": "THREE"}]


def message(text="yes", **changes):
    return IncomingMessage(**{"text": text, "sender_id": "+15555550123", "platform": "imessage",
        "message_id": "event-1", "conversation_type": "dm", **changes})


class Members:
    def resolve(self, platform, sender):
        return {"code": "ONE"} if sender == "+15555550123" else None

    def aliases(self, semester):
        return deepcopy(ALIASES)

    def list_active(self):
        return [{"code": "ONE", "display_name": "Demo One", "skills": ["Logistics"]},
                {"code": "TWO", "display_name": "Demo Two", "skills": ["Logistics"]}]


class Tasks:
    def __init__(self):
        self.rows = {TASK["id"]: deepcopy(TASK)}

    def get(self, task_id):
        if task_id not in self.rows:
            raise TaskNotFound()
        return deepcopy(self.rows[task_id])

    def by_task_code(self, code, semester):
        return next((deepcopy(t) for t in self.rows.values() if t["task_code"] == code), None)

    def unfinished_for_semester(self, semester):
        return list(deepcopy(self.rows).values())


class Store:
    def __init__(self):
        self.offers = [{"task_id": TASK["id"], "due_date": TASK["due_date"]}]
        self.saved = []
        self.calls = []
        self.row = {"request_no": 1, "requester_code": "ONE", "selected_code": "TWO",
            "task_id": TASK["id"], "task_version": "version-1", "status": "awaiting_recommendations",
            "candidates": [], "revision": 1}

    def recent_offers(self, member, sender, now):
        return deepcopy(self.offers)

    def request(self, msg, member, task, digest, semester):
        self.saved.append(task["id"])
        return {"reply": "Saved help request HELP-1", "request_no": 1}

    def receipt(self, msg):
        return self.row

    def get(self, number):
        return self.row

    def group(self, group_id):
        return self.row if group_id == "known-group" else None

    def is_admin(self, code):
        return False

    def rpc(self, name, **values):
        self.calls.append((name, values))
        return {"reply": "Saved"}


def config(**changes):
    return SimpleNamespace(**{"active_semester": "fall-2026", "help_workflow_enabled": True,
        "gemini_api_key": "fake", "gemini_model": "test", **changes})


def test_yes_requires_one_recent_valid_owned_offer_and_no_does_not_write():
    tasks, store = Tasks(), Store()
    assert "Saved" in help_request_reply(message(), Members(), tasks, store, "fall-2026")
    assert store.saved == [TASK["id"]]
    store.saved.clear()
    assert "no help request" in help_request_reply(message("no thanks"), Members(), tasks, store, "fall-2026")
    assert not store.saved
    store.offers = []
    assert help_request_reply(message(), Members(), tasks, store, "fall-2026") is None
    assert not store.saved


def test_yes_to_ambiguous_offers_asks_for_task_code_without_writing():
    tasks, store = Tasks(), Store()
    second = {**TASK, "id": "other-task", "task_code": "WIN-202610-2", "title": "Make flyer"}
    tasks.rows[second["id"]] = second
    store.offers.append({"task_id": second["id"], "due_date": second["due_date"]})
    assert "Which check-in" in help_request_reply(message(), Members(), tasks, store, "fall-2026")
    assert not store.saved


@pytest.mark.parametrize("changes", [{"assignee_text": "Demo Two"}, {"status": "done"},
                                    {"semester_code": "spring-2027"}, {"due_date": "2026-11-21"}])
def test_stale_or_foreign_offer_cannot_become_a_help_request(changes):
    tasks, store = Tasks(), Store()
    tasks.rows[TASK["id"]].update(changes)
    assert help_request_reply(message(), Members(), tasks, store, "fall-2026") is None
    assert not store.saved


def test_transfer_preserves_other_coowners_and_requires_verified_aliases():
    result = transfer_assignment({**TASK, "assignee_text": "Demo One; Demo Three"},
        {"requester_code": "ONE", "selected_code": "TWO"}, Members(), "fall-2026")
    assert set(result.split("; ")) == {"Demo Two", "Demo Three"}
    with pytest.raises(ValueError, match="alias"):
        transfer_assignment(TASK, {"requester_code": "ONE", "selected_code": "UNKNOWN"}, Members(), "fall-2026")


@pytest.mark.asyncio
async def test_existing_recommender_is_reused_but_does_not_transfer(monkeypatch):
    store = Store()
    recommender = AsyncMock(return_value=[{"code": "TWO", "name": "Demo Two", "reason": "Logistics skills", "open": 2}])
    monkeypatch.setattr("app.services.help_workflow.suggest_candidates", recommender)
    monkeypatch.setattr("app.services.help_workflow.load_skills", dict)
    reply = await help_workflow_reply(message("help WIN-202610-1"), Members(), Tasks(), store, config())
    assert "choose HELP-1" in reply and "admin approval" in reply
    recommender.assert_awaited_once()
    assert [v["p_action"] for _, v in store.calls] == ["candidates"]


@pytest.mark.asyncio
async def test_only_requester_can_choose_and_only_saved_choice_is_sent_to_rpc():
    store = Store()
    await help_workflow_reply(message("choose HELP-1 TWO"), Members(), Tasks(), store, config())
    assert store.calls[0][1]["p_action"] == "select"
    store.calls.clear()
    store.row["requester_code"] = "OTHER"
    assert "couldn't find" in await help_workflow_reply(message("choose HELP-1 TWO"), Members(), Tasks(), store, config())
    assert not store.calls
    assert "Only a designated" in await help_workflow_reply(message("approve HELP-1 v2"), Members(), Tasks(), store, config())
    assert not store.calls


def test_bound_group_task_store_cannot_reveal_or_change_another_task():
    bound = HandoffTasks(Tasks(), TASK)
    assert bound.by_task_code("WIN-202610-2", "fall-2026") is None
    with pytest.raises(TaskNotFound):
        bound.get("other-task")
    assert len(bound.unfinished_for_semester("fall-2026")) == 1


@pytest.mark.asyncio
async def test_only_known_groups_and_verified_participants_can_report_updates():
    store = Store()
    async def run(msg):
        return await group_reply(msg, Members(), Tasks(), None, None, store, config())
    assert await run(message("update waiting for confirmation", conversation_type="group", space_id="unrelated")) is None
    assert not store.calls
    assert "Saved" in await run(message("update waiting for confirmation", conversation_type="group", space_id="known-group"))
    assert store.calls[0][0] == "report_help_group"
    store.calls.clear()
    assert await run(message("update hi", conversation_type="group", space_id="known-group", sender_id="other")) is None
    assert not store.calls


@pytest.mark.asyncio
async def test_natural_completion_in_group_uses_only_bound_task_and_notifies_admin():
    store, tasks = Store(), Tasks()
    tasks.rows[TASK["id"]]["assignee_text"] = "Demo Two"
    tasks.rows["foreign"] = {**TASK, "id": "foreign", "title": "Private unrelated task"}

    class NewOwner(Members):
        def resolve(self, platform, sender):
            return {"code": "TWO"}

    class Interpreter:
        def interpret(self, text, selected):
            assert [t["id"] for t in selected] == [TASK["id"]]
            return {"intent": "complete_task", "task_ids": [TASK["id"]], "completion_asserted": True,
                    "evidence_quote": text, "confidence": 0.99, "reply": "Completed"}

    class Completions:
        def receipt(self, *args):
            return None

        def complete(self, msg, member, task, digest, semester):
            tasks.rows[task["id"]]["status"] = "done"
            return {"reply": "Marked WIN-202610-1 done."}

    reply = await group_reply(message("I finished booking the room.", conversation_type="group", space_id="known-group"),
        NewOwner(), tasks, Completions(), Interpreter(), store, config(message_ai_enabled=True,
            message_ai_max_tasks=60))
    assert reply == "Marked WIN-202610-1 done."
    assert tasks.rows["foreign"]["status"] == "todo"
    assert not store.calls  # Admin completion notification belongs to the SQL transaction.


def test_admin_approval_api_has_no_development_auth_bypass(monkeypatch):
    monkeypatch.setenv("WINNIE_HELP_ADMIN_API_KEY", "")
    with TestClient(app) as client:
        assert client.get("/api/help-requests").status_code == 401
    monkeypatch.setenv("WINNIE_HELP_ADMIN_API_KEY", "test-admin-key")
    with TestClient(app) as client:
        assert client.get("/api/help-requests").status_code == 401
        assert client.post("/api/internal/help/next", json={}).status_code == 401
