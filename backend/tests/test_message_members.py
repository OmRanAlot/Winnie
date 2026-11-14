"""Synthetic member identities only; personal task access must fail closed."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.integrations.supabase import StorageUnavailable
from app.main import app
from app.routes import messages
from app.services.members import AliasConflict, MemberStore, assignment_members, normalize_sender
from app.services.message_replies import personal_reply
from app.services.tasks import TaskStore

ALIASES = [
    {"alias": "Avery Chen", "member_code": "AVERY"},
    {"alias": "avery@example.test", "member_code": "AVERY"},
    {"alias": "Morgan Lee", "member_code": "MORGAN"},
]
SECRET = "synthetic-test-bridge-secret"


class Members:
    def __init__(self, known=True):
        self.known = known

    def resolve(self, platform, sender_id):
        if self.known and platform == "imessage" and sender_id == "+15555550123":
            return {"code": "AVERY", "display_name": "Avery", "active": True}
        return None

    def aliases(self, semester):
        assert semester == "fall-2026"
        return ALIASES


class Tasks:
    def unfinished_for_semester(self, semester):
        assert semester == "fall-2026"
        return [
            task("other", "Morgan Lee", "2026-01-01"),
            task("no-date", "Avery Chen", None),
            task("late", "Avery Chen", "2026-12-10"),
            task("early", "avery@example.test Morgan Lee", "2026-11-20", "in_progress"),
            task("unknown", "Avery Chen Unknown Person", "2026-11-01"),
        ]


def task(title, assignee, due, status="todo"):
    return {
        "id": title, "title": title, "assignee_text": assignee,
        "due_date": due, "status": status,
    }


def message(**changes):
    return messages.IncomingMessage(**{
        "text": "tasks", "sender_id": "+15555550123",
        "platform": "imessage", "conversation_type": "dm", **changes,
    })


def test_full_names_emails_and_shared_assignments():
    assert assignment_members("Avery Chen", ALIASES) == {"AVERY"}
    assert assignment_members(" AVERY@example.test Morgan Lee ", ALIASES) == {"AVERY", "MORGAN"}
    assert assignment_members("Avery Chen & Morgan Lee", ALIASES) == {"AVERY", "MORGAN"}
    assert assignment_members("Avery Chen and Morgan Lee", ALIASES) == {"AVERY", "MORGAN"}
    assert assignment_members("Avery Chen avery@example.test", ALIASES) == {"AVERY"}


def test_partial_substrings_unknown_people_and_conflicting_aliases_do_not_match():
    assert assignment_members("Avery Chens", ALIASES) is None
    assert assignment_members("Avery Chen Unknown Person", ALIASES) is None
    assert assignment_members("avery@example.test.attacker", ALIASES) is None
    assert assignment_members("", ALIASES) == set()
    with pytest.raises(AliasConflict):
        assignment_members("Avery Chen", [*ALIASES, {"alias": "AVERY CHEN", "member_code": "OTHER"}])


def test_ambiguous_shared_name_segmentation_is_not_guessed():
    aliases = [
        {"alias": "Avery Chen", "member_code": "AVERY"},
        {"alias": "Avery", "member_code": "OTHER1"},
        {"alias": "Chen", "member_code": "OTHER2"},
    ]
    assert assignment_members("Avery Chen", aliases) is None


def test_reassignment_owner_controls_personal_task_visibility():
    class ReassignedTasks:
        def unfinished_for_semester(self, semester):
            return [
                {**task("Assigned to you", "Unknown Alias", None), "owner_code": "AVERY"},
                {**task("Assigned away", "Avery Chen", None), "owner_code": "MORGAN"},
            ]

    reply = personal_reply(message(), Members(), ReassignedTasks(), "fall-2026")
    assert "Assigned to you" in reply
    assert "Assigned away" not in reply


def test_task_list_is_personal_ordered_and_has_no_other_members_task():
    reply = personal_reply(message(), Members(), Tasks(), "fall-2026")
    assert "1. early" in reply
    assert "2. late" in reply
    assert "3. no-date" in reply
    assert "other -" not in reply
    assert "unknown -" not in reply
    assert "in progress" in reply
    assert "may be incomplete" in reply


def test_personal_limit_applies_after_member_filter():
    class ManyTasks:
        def unfinished_for_semester(self, semester):
            return [task(f"theirs-{i}", "Morgan Lee", "2026-01-01") for i in range(10)] + [
                task(f"mine-{i}", "Avery Chen", "2026-11-20") for i in range(7)
            ]

    reply = personal_reply(message(), Members(), ManyTasks(), "fall-2026")
    assert reply.count("[todo]") == 5
    assert "theirs" not in reply


def test_unknown_sender_never_gets_task_data_or_self_enrolls():
    class NoTasks:
        def unfinished_for_semester(self, semester):
            pytest.fail("Unknown sender must not reach task storage")

    reply = personal_reply(message(), Members(known=False), NoTasks(), "fall-2026")
    assert "not linked" in reply
    setup = personal_reply(message(text="whoami"), Members(False), NoTasks(), "fall-2026")
    assert "Sender ID: +15555550123" in setup


@pytest.mark.parametrize("kind", ["group", "unknown"])
def test_personal_data_not_returned_into_groups_or_unknown_spaces(kind):
    reply = personal_reply(message(conversation_type=kind), None, None, "fall-2026")
    assert "direct conversation" in reply
    assert "+15555550123" not in reply


def test_missing_sender_and_wrong_platform_are_not_trusted():
    for data in (message(sender_id=None), message(platform="other")):
        assert "could not identify" in personal_reply(data, None, None, "fall-2026")


def test_known_whoami_does_not_read_tasks():
    assert personal_reply(message(text="2"), Members(), None, "fall-2026") == (
        "You are linked to Avery (AVERY)."
    )


def test_normalize_sender_preserves_phone_and_normalizes_email():
    assert normalize_sender(" +15555550123 ") == "+15555550123"
    assert normalize_sender(" Avery@Example.Test ") == "avery@example.test"


def test_inactive_member_is_not_resolved():
    store = MemberStore()
    responses = iter([
        SimpleNamespace(data=[{"member_code": "AVERY"}]), SimpleNamespace(data=[]),
    ])
    operations = []

    class Query:
        def select(self, fields):
            return self

        def eq(self, name, value):
            operations.append((name, value))
            return self

    def execute(table, operation):
        operation(Query())
        return next(responses)

    store._execute = execute
    assert store.resolve("imessage", "+15555550123") is None
    assert ("active", True) in operations


def test_unfinished_query_paginates_and_orders_deadlines_before_filtering():
    calls = []

    class Query:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                calls.append((name, args, kwargs))
                return self
            return method

    store = TaskStore()
    pages = iter([SimpleNamespace(data=[{}] * 500), SimpleNamespace(data=[{}])])

    def execute(operation):
        operation(Query())
        return next(pages)

    store._execute = execute
    assert len(store.unfinished_for_semester("fall-2026")) == 501
    assert ("eq", ("semester_code", "fall-2026"), {}) in calls
    assert ("neq", ("status", "done"), {}) in calls
    assert ("order", ("due_date",), {"nullsfirst": False}) in calls
    assert ("range", (500, 999), {}) in calls


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WINNIE_MESSAGING_BRIDGE_SECRET", SECRET)
    monkeypatch.setenv("WINNIE_ACTIVE_SEMESTER", "fall-2026")
    app.dependency_overrides[messages.get_member_store] = Members
    app.dependency_overrides[messages.get_task_store] = Tasks
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_http_sender_claim_needs_the_bridge_secret(client):
    payload = message().model_dump()
    assert client.post("/api/messages", json=payload).status_code == 401
    assert client.post("/api/messages", json=payload, headers={
        "X-Winnie-Bridge-Secret": "wrong",
    }).status_code == 401
    response = client.post("/api/messages", json=payload, headers={
        "X-Winnie-Bridge-Secret": SECRET,
    })
    assert response.status_code == 200
    assert "1. early" in response.json()["reply"]


def test_unconfigured_bridge_does_not_open_personal_access(client, monkeypatch):
    monkeypatch.setenv("WINNIE_MESSAGING_BRIDGE_SECRET", "")
    assert client.post("/api/messages", json=message().model_dump()).status_code == 503


def test_ping_and_help_remain_available_without_private_data(client):
    assert client.post("/api/messages", json={"text": "ping"}).json()["reply"] == "pong 🏓"
    assert "Choose an option" in client.post("/api/messages", json={"text": "help"}).json()["reply"]


def test_storage_failure_returns_clear_reply_without_provider_details(client):
    class OfflineMembers:
        def resolve(self, platform, sender_id):
            raise StorageUnavailable("private provider diagnostic")

    app.dependency_overrides[messages.get_member_store] = OfflineMembers
    response = client.post("/api/messages", json=message().model_dump(), headers={
        "X-Winnie-Bridge-Secret": SECRET,
    })
    assert response.status_code == 200
    assert "couldn't load" in response.json()["reply"]
    assert "private provider" not in response.text
