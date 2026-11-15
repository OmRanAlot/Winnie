"""Crafted HTTP writes exercise both task routes using a synthetic canonical store."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.db import repository
from app.main import app
from app.routes.tasks import get_task_members, get_task_store
from app.services.tasks import TaskStore
from tests.fake_supabase import FakeClient

TASK_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def board(signed_in_member, monkeypatch):
    actor = signed_in_member
    actor.profile.update(is_admin=False, member_code="ALICE")
    db = FakeClient()
    db.postgrest = SimpleNamespace(session=SimpleNamespace(close=lambda: None))
    db.table("tasks").insert({
        "id": TASK_ID, "title": "Synthetic task", "month_code": "2026-11",
        "semester_code": Settings().active_semester, "owner_code": "ALICE",
    }).execute()
    aliases = [{"alias": "Alice", "member_code": "ALICE"},
               {"alias": "Bob", "member_code": "BOB"}]
    members = SimpleNamespace(aliases=lambda semester: aliases)
    store = TaskStore(lambda: db)
    monkeypatch.setitem(app.dependency_overrides, get_task_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, get_task_members, lambda: members)
    monkeypatch.setattr(repository, "get_client", lambda: db)
    with TestClient(app) as client:
        yield client, db.tables["tasks"][0], actor, store, aliases


def patch(client, route, changes=None):
    path = f"/api/tasks/records/{TASK_ID}" if route == "records" else f"/api/tasks/{TASK_ID}/status"
    return client.patch(path, json=changes or {"status": "done"})


@pytest.mark.parametrize("route", ["records", "timeline"])
@pytest.mark.parametrize("assignment,allowed", [
    ({"owner_code": "ALICE"}, True),
    ({"owner_code": "BOB", "assignee_text": "Alice"}, False),
    ({"owner_code": None, "assignee_text": "Alice and Bob"}, True),
    ({"owner_code": None, "assignee_text": "Alice and unknown"}, False),
    ({"owner_code": None, "assignee_text": "Al"}, False),
    ({"owner_code": None, "assignee_text": ""}, False),
    ({"semester_code": "fall-2020"}, False),
])
def test_member_status_writes_require_verified_current_assignment(board, route, assignment, allowed):
    client, row, _, _, _ = board
    row.update(assignment)
    response = patch(client, route)
    assert response.status_code == (200 if allowed else 403)
    assert row["status"] == ("done" if allowed else "todo")


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("changes", [
    {"owner_code": "BOB"}, {"owner_code": None}, {"assignee_text": "Bob"},
    {"owner_code": "ALICE", "status": "done"},
])
def test_general_edit_cannot_bypass_reassignment_even_for_admin(board, admin, changes):
    client, row, actor, _, _ = board
    actor.profile["is_admin"] = admin
    response = patch(client, "records", changes)
    assert response.status_code == 403
    assert "reassignment request" in response.json()["detail"]
    assert row["owner_code"] == "ALICE" and row["status"] == "todo"


@pytest.mark.parametrize("changes", [
    {"title": "Changed"}, {"description": "Changed"}, {"due_date": "2026-12-01"},
    {"stakeholder_codes": ["BOB"]}, {"priority": "high"},
    {"notes": "Allowed alone", "title": "Forbidden"},
])
def test_member_cannot_edit_admin_fields(board, changes):
    client, row, _, _, _ = board
    assert patch(client, "records", changes).status_code == 403
    assert row["title"] == "Synthetic task" and row["status"] == "todo"


def test_notes_are_persisted_only_for_assigned_member(board):
    client, row, _, _, _ = board
    assert patch(client, "records", {"notes": "Progress"}).status_code == 200
    row["owner_code"] = "BOB"
    assert patch(client, "records", {"notes": "Overwrite"}).status_code == 403
    assert row["notes"] == "Progress"


@pytest.mark.parametrize("route", ["records", "timeline"])
def test_ambiguous_aliases_fail_closed(board, route):
    client, row, _, _, aliases = board
    row.update(owner_code=None, assignee_text="Alice")
    aliases.append({"alias": "Alice", "member_code": "BOB"})
    assert patch(client, route).status_code == 403
    assert row["status"] == "todo"


@pytest.mark.parametrize("route", ["records", "timeline"])
@pytest.mark.parametrize("admin", [False, True])
def test_reassignment_between_check_and_write_is_conflict(board, monkeypatch, route, admin):
    client, row, actor, store, _ = board
    actor.profile["is_admin"] = admin
    update = store.update_if_current

    def raced(task_id, changes, updated_at):
        row.update(owner_code="BOB", updated_at="2026-12-01T12:00:00Z")
        return update(task_id, changes, updated_at)

    monkeypatch.setattr(store, "update_if_current", raced)
    assert patch(client, route).status_code == 409
    assert row["owner_code"] == "BOB" and row["status"] == "todo"


def test_admin_can_edit_metadata_and_other_owners_status(board):
    client, row, actor, _, _ = board
    actor.profile["is_admin"] = True
    row["owner_code"] = "BOB"
    assert patch(client, "records", {"title": "Reviewed", "due_date": "2026-12-01"}).status_code == 200
    assert patch(client, "timeline").status_code == 200
    assert row["title"] == "Reviewed" and row["status"] == "done"


def test_legacy_open_status_still_works_for_authorized_member(board):
    client, row, _, _, _ = board
    row["status"] = "done"
    assert patch(client, "timeline", {"status": "open"}).status_code == 200
    assert row["status"] == "todo"


@pytest.mark.parametrize("route", ["records", "timeline"])
def test_missing_revision_fails_closed(board, route):
    client, row, _, _, _ = board
    row["updated_at"] = None
    assert patch(client, route).status_code == 503
    assert row["status"] == "todo"
