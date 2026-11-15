"""Tests for app/db/repository.py against the in-memory FakeClient (no live Supabase)."""

from datetime import datetime

import pytest

from app.core.deadlines import NEW_YORK
from app.db import repository as repo
from app.domain.models import ExtractedTask
from tests.fake_supabase import FakeClient

MEETING_AT = datetime(2026, 11, 13, 18, 0, tzinfo=NEW_YORK)  # a Friday


@pytest.fixture
def db() -> FakeClient:
    return FakeClient()


def extracted(**overrides) -> ExtractedTask:
    fields = {
        "title": "Check alternate room booking",
        "description": "Find a backup room for the GBM.",
        "seat": "Vice President",
        "assignee": "Bob Newman",
        "rationale": "Bob agreed to handle the room booking.",
        "deadline": "by Monday noon",
        "needs_review": False,
    }
    return ExtractedTask(**{**fields, **overrides})


# --- seats ------------------------------------------------------------------------------------


def test_get_or_create_seat_is_idempotent(db):
    first = repo.get_or_create_seat("Treasurer", client=db)
    assert repo.get_or_create_seat("  Treasurer ", client=db) == first
    assert len(db.tables["seats"]) == 1


def test_get_or_create_seat_rejects_blank(db):
    with pytest.raises(ValueError):
        repo.get_or_create_seat("   ", client=db)


# --- people -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "people,query,expected",
    [
        ([{"id": 1, "name": "Bob Newman", "aliases": []}], "bob newman", 1),
        ([{"id": 1, "name": "Bob Newman", "aliases": ["Bobby"]}], "BOBBY", 1),
        ([{"id": 1, "name": "Bob Newman", "aliases": []}], "Bob", 1),
        ([{"id": 1, "name": "Bob", "aliases": []}], "Bob Newman", 1),
        # Two Bobs: a bare first name is ambiguous, so no match (a new person is created).
        (
            [{"id": 1, "name": "Bob Newman", "aliases": []}, {"id": 2, "name": "Bob Ross", "aliases": []}],
            "Bob",
            None,
        ),
        ([{"id": 1, "name": "Bob Newman", "aliases": []}], "Bob Ross", None),
        ([{"id": 1, "name": "Alice", "aliases": []}], "Sam", None),
        # The same alias on two people is ambiguous too.
        (
            [{"id": 1, "name": "Bob Newman", "aliases": ["B"]}, {"id": 2, "name": "Boba", "aliases": ["b"]}],
            "b",
            None,
        ),
    ],
)
def test_match_person(people, query, expected):
    match = repo.match_person(query, people)
    assert (match["id"] if match else None) == expected


def test_get_or_create_person_resolves_short_and_full_names_to_one_person(db):
    bob = repo.get_or_create_person("Bob Newman", client=db)
    assert repo.get_or_create_person("bob", client=db) == bob
    assert repo.get_or_create_person("BOB NEWMAN", client=db) == bob
    [row] = db.tables["people"]
    assert row["name"] == "Bob Newman"
    assert row["aliases"] == []  # first-name guesses are never saved as aliases


def test_get_or_create_person_matches_short_name_created_first(db):
    bob = repo.get_or_create_person("Bob", client=db)
    assert repo.get_or_create_person("Bob Newman", client=db) == bob


def test_first_name_guess_does_not_stick_once_ambiguous(db):
    newman = repo.get_or_create_person("Bob Newman", client=db)
    assert repo.get_or_create_person("Bob", client=db) == newman
    ross = repo.get_or_create_person("Bob Ross", client=db)
    assert ross != newman
    # With two Bobs, "Bob" no longer silently resolves to the first one.
    assert repo.match_person("Bob", db.tables["people"]) is None


def test_find_or_create_meeting_is_idempotent_per_recording(db):
    first, created = repo.find_or_create_meeting(MEETING_AT, "GBM", None, "rec-1", client=db)
    again, created_again = repo.find_or_create_meeting(MEETING_AT, "GBM", None, "rec-1", client=db)
    other, _ = repo.find_or_create_meeting(MEETING_AT, "GBM", None, "rec-2", client=db)
    assert (created, created_again) == (True, False)
    assert again == first and other != first
    repo.insert_extracted_tasks(first, [extracted()], client=db)
    assert [t.title for t in repo.tasks_for_meeting(first, client=db)] == ["Check alternate room booking"]
    assert repo.tasks_for_meeting(other, client=db) == []


def test_get_or_create_person_creates_distinct_people(db):
    assert repo.get_or_create_person("Alice", client=db) != repo.get_or_create_person("Sam", client=db)


def test_get_or_create_person_rejects_blank(db):
    with pytest.raises(ValueError):
        repo.get_or_create_person("", client=db)


# --- meetings and tasks -----------------------------------------------------------------------


def test_insert_extracted_tasks_resolves_seat_person_and_deadline(db):
    meeting_id = repo.create_meeting(MEETING_AT, "GBM planning", "transcript", client=db)
    [task] = repo.insert_extracted_tasks(meeting_id, [extracted()], client=db)

    assert task.title == "Check alternate room booking"
    assert task.seat == "Vice President"
    assert task.assignee == "Bob Newman"
    assert task.deadline_raw == "by Monday noon"
    assert task.deadline_at == datetime(2026, 11, 16, 12, 0, tzinfo=NEW_YORK)
    assert task.status == "todo"
    assert task.source_meeting_id == meeting_id
    assert task.meeting_held_at == MEETING_AT
    assert task.raw_json["assignee"] == "Bob Newman"


def test_insert_extracted_tasks_uses_one_batch_upsert(db):
    meeting_id = repo.create_meeting(MEETING_AT, None, None, client=db)
    tasks = [extracted(title=f"Task {n}") for n in range(3)]
    repo.insert_extracted_tasks(meeting_id, tasks, client=db)
    assert db.calls.count(("tasks", "upsert")) == 1
    assert db.tables["seats"] == [] and db.tables["people"] == []


def test_meeting_tasks_use_canonical_fields_and_repeat_insert_is_idempotent(db):
    from uuid import UUID

    meeting = repo.create_meeting(MEETING_AT, None, None, client=db)
    [task] = repo.insert_extracted_tasks(meeting, [extracted()], client=db)
    [again] = repo.insert_extracted_tasks(meeting, [extracted()], client=db)
    assert UUID(task.id) and again.id == task.id
    assert len(db.tables["tasks"]) == 1
    [row] = db.tables["tasks"]
    assert row["month_code"] == "2026-11" and row["semester_code"] == "fall-2026"
    assert row["source"] == "meeting" and row["status"] == "todo"
    assert row["due_date"] == "2026-11-16"
    assert row["assignee_text"] == "Bob Newman" and row["owner_code"] is None
    assert not {"seat_id", "assignee_id", "deadline_raw"} & row.keys()


def test_tracker_tasks_share_timeline_and_due_date_edits_override_extraction(db):
    db.table("tasks").insert({
        "title": "Tracker task", "month_code": "2026-11", "owner_code": "DEMO",
        "status": "in_progress", "due_date": "2026-11-20", "source": "sheet",
    }).execute()
    [tracker] = repo.list_tasks(client=db)
    assert tracker.status == "in_progress" and tracker.assignee_id == "DEMO"
    assert tracker.deadline_at == datetime(2026, 11, 20, tzinfo=NEW_YORK)
    meeting = repo.create_meeting(MEETING_AT, None, None, client=db)
    [task] = repo.insert_extracted_tasks(meeting, [extracted()], client=db)
    db.table("tasks").update({"due_date": "2026-12-01"}).eq("id", task.id).execute()
    [changed] = repo.tasks_for_meeting(meeting, client=db)
    assert changed.deadline_at == datetime(2026, 12, 1, tzinfo=NEW_YORK)
    db.table("tasks").update({"due_date": None}).eq("id", task.id).execute()
    assert repo.tasks_for_meeting(meeting, client=db)[0].deadline_at is None


def test_legacy_open_input_is_stored_as_todo(db):
    task = seed_three(db)[0]
    repo.update_task_status(task.id, "done", client=db)
    assert repo.update_task_status(task.id, "open", client=db).status == "todo"


def test_unassigned_and_unparseable_tasks_keep_nulls(db):
    meeting_id = repo.create_meeting(MEETING_AT, None, None, client=db)
    [task] = repo.insert_extracted_tasks(
        meeting_id,
        [extracted(seat="Unassigned", assignee=None, deadline="sometime soon", needs_review=True)],
        client=db,
    )
    assert task.seat_id is None and task.assignee_id is None
    assert task.deadline_raw == "sometime soon"
    assert task.deadline_at is None
    assert task.needs_review is True


def test_insert_extracted_tasks_with_no_tasks_writes_nothing(db):
    meeting_id = repo.create_meeting(MEETING_AT, None, None, client=db)
    assert repo.insert_extracted_tasks(meeting_id, [], client=db) == []
    assert ("tasks", "upsert") not in db.calls


def test_insert_extracted_tasks_unknown_meeting_raises(db):
    with pytest.raises(repo.NotFound):
        repo.insert_extracted_tasks(999, [extracted()], client=db)


def seed_three(db: FakeClient) -> list:
    meeting_id = repo.create_meeting(MEETING_AT, "GBM", None, client=db)
    return repo.insert_extracted_tasks(
        meeting_id,
        [
            extracted(title="Late", deadline="Wednesday"),
            extracted(title="No deadline", deadline=None, seat="Treasurer", assignee="Sam"),
            extracted(title="Early", deadline="tonight", seat="Treasurer", assignee="Sam"),
        ],
        client=db,
    )


def test_list_tasks_orders_by_deadline_with_unscheduled_last(db):
    seed_three(db)
    assert [t.title for t in repo.list_tasks(client=db)] == ["Early", "Late", "No deadline"]


def test_list_tasks_filters(db):
    _, _, early = seed_three(db)
    repo.update_task_status(early.id, "done", client=db)

    assert [t.title for t in repo.list_tasks(assignee="sam", client=db)] == ["Early", "No deadline"]
    assert [t.title for t in repo.list_tasks(assignee="Bob", client=db)] == ["Late"]
    assert [t.title for t in repo.list_tasks(seat="treasurer", client=db)] == ["Early", "No deadline"]
    assert [t.title for t in repo.list_tasks(status="done", client=db)] == ["Early"]
    assert [t.title for t in repo.list_tasks(status="open", seat="Treasurer", client=db)] == [
        "No deadline"
    ]
    assert repo.list_tasks(assignee="Nobody", client=db) == []
    assert repo.list_tasks(seat="Nonexistent", client=db) == []


def test_list_tasks_rejects_unknown_status(db):
    with pytest.raises(ValueError):
        repo.list_tasks(status="finished", client=db)


def test_update_task_status(db):
    task = seed_three(db)[0]
    updated = repo.update_task_status(task.id, "blocked", client=db)
    assert updated.status == "blocked"
    assert updated.seat == "Vice President"


def test_update_task_status_validates(db):
    task = seed_three(db)[0]
    with pytest.raises(ValueError):
        repo.update_task_status(task.id, "finished", client=db)
    with pytest.raises(repo.NotFound):
        repo.update_task_status("00000000-0000-4000-8000-000000000999", "done", client=db)


# --- dependencies ----------------------------------------------------------------------------


def test_add_dependency_shows_up_on_the_task(db):
    a, b, _ = seed_three(db)
    repo.add_dependency(a.id, b.id, client=db)
    repo.add_dependency(a.id, b.id, client=db)  # idempotent
    [listed] = [t for t in repo.list_tasks(client=db) if t.id == a.id]
    assert listed.depends_on == (b.id,)


def test_add_dependency_rejects_self_and_cycles(db):
    a, b, c = seed_three(db)
    with pytest.raises(ValueError):
        repo.add_dependency(a.id, a.id, client=db)
    repo.add_dependency(a.id, b.id, client=db)
    repo.add_dependency(b.id, c.id, client=db)
    with pytest.raises(ValueError, match="cycle"):
        repo.add_dependency(c.id, a.id, client=db)


def test_add_dependency_unknown_task(db):
    a, *_ = seed_three(db)
    with pytest.raises(repo.NotFound):
        repo.add_dependency(a.id, "00000000-0000-4000-8000-000000000999", client=db)


def test_add_dependencies_is_idempotent_and_rejects_cyclic_batch(db):
    a, b, c = seed_three(db)
    added = repo.add_dependencies([(a.id, b.id), (b.id, c.id)], client=db)
    assert [(edge.task_id, edge.depends_on_id) for edge in added] == [(a.id, b.id), (b.id, c.id)]
    assert repo.add_dependencies([(a.id, b.id), (b.id, c.id)], client=db) == []

    with pytest.raises(ValueError, match="cycle"):
        repo.add_dependencies([(c.id, a.id)], client=db)
    assert len(db.tables["task_dependencies"]) == 2


def test_would_create_cycle():
    edges = [(1, 2), (2, 3)]
    assert repo.would_create_cycle(edges, task_id=3, depends_on_id=1)
    assert not repo.would_create_cycle(edges, task_id=1, depends_on_id=3)
