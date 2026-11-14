"""Reminder clocks and orchestration use fictional tasks and no real sends."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.reminders import next_reminder, reminder_slots, scan_reminders


def at(text):
    return datetime.fromisoformat(text)


def task(**changes):
    return {
        "id": "11111111-1111-4111-8111-111111111111", "task_code": "WIN-202610-1",
        "title": "Book workshop room", "due_date": "2026-11-20", "status": "todo",
        "created_at": "2026-10-01T12:00:00+00:00", "assignee_text": "Demo One",
        "semester_code": "fall-2026", **changes,
    }


def settings(**changes):
    return SimpleNamespace(**{
        "reminders_enabled": True, "reminder_transport": "mock",
        "reminder_timezone": "America/New_York", "reminder_daytime_hour": 9,
        "reminder_evening_hour": 18, "active_semester": "fall-2026", **changes,
    })


def test_five_reminder_windows_are_local_calendar_times_and_do_not_overlap():
    expected = [
        ("2026-11-06T14:00:00+00:00", "fourteen_day"),
        ("2026-11-13T14:00:00+00:00", "seven_day"),
        ("2026-11-15T14:00:00+00:00", "five_day_help"),
        ("2026-11-17T14:00:00+00:00", "three_day"),
        ("2026-11-19T23:00:00+00:00", "previous_evening"),
    ]
    for stamp, kind in expected:
        slots = reminder_slots(task(), at(stamp))
        assert len(slots) == 1
        assert slots[0]["kind"] == kind
        assert slots[0]["scheduled_at"] == stamp
    assert not reminder_slots(task(), at("2026-11-20T05:00:00+00:00"))
    assert not reminder_slots(task(), at("2026-11-05T14:00:00+00:00"))


def test_dst_changes_use_calendar_days_not_24_hour_subtraction():
    spring = task(due_date="2027-03-16")
    early = reminder_slots(spring, at("2027-03-09T14:00:00+00:00"))[0]
    evening = reminder_slots(spring, at("2027-03-15T22:00:00+00:00"))[0]
    assert early["scheduled_at"] == "2027-03-09T14:00:00+00:00"
    assert evening["scheduled_at"] == "2027-03-15T22:00:00+00:00"
    fall = task(due_date="2026-11-03")
    assert reminder_slots(fall, at("2026-10-27T13:00:00+00:00"))[0]["scheduled_at"] == (
        "2026-10-27T13:00:00+00:00"
    )
    assert reminder_slots(fall, at("2026-11-02T23:00:00+00:00"))[0]["scheduled_at"] == (
        "2026-11-02T23:00:00+00:00"
    )


def test_short_notice_creation_or_changed_schedule_skips_past_triggers():
    recent = task(created_at="2026-11-18T12:00:00+00:00")
    assert not reminder_slots(recent, at("2026-11-18T14:00:00+00:00"))
    assert reminder_slots(recent, at("2026-11-19T23:00:00+00:00"))[0]["kind"] == "previous_evening"
    edited = task(reminder_schedule_started_at="2026-11-18T12:00:00+00:00")
    assert not reminder_slots(edited, at("2026-11-18T14:00:00+00:00"))


@pytest.mark.parametrize("changes", [{"status": "done"}, {"due_date": None}])
def test_completed_or_undated_tasks_never_produce_reminders(changes):
    assert not reminder_slots(task(**changes), at("2026-11-17T14:00:00+00:00"))


def test_naive_demo_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        reminder_slots(task(), datetime(2026, 11, 17))


class Tasks:
    def __init__(self, rows=None):
        self.rows = rows or [task()]

    def unfinished_for_semester(self, semester):
        return deepcopy(self.rows)

    def get(self, task_id):
        return deepcopy(next(row for row in self.rows if row["id"] == task_id))


class Members:
    def aliases(self, semester):
        return [{"alias": "Demo One", "member_code": "ONE"}]


class Store:
    def __init__(self):
        self.items = {}
        self.outcomes = []

    def recipients(self):
        return [{"member_code": "ONE", "sender_id": "+15555550123", "platform": "imessage"}]

    def queue(self, source, recipient, slot, body, transport, now):
        key = (source["id"], recipient["member_code"], source["due_date"], slot["kind"], transport)
        if key in self.items:
            return None
        self.items[key] = {
            **recipient, "task_id": source["id"], "id": str(len(self.items)), "claim_token": "token",
            "kind": slot["kind"],
            "transport": transport, "body": body, "status": "pending",
        }
        return self.items[key]["id"]

    def claim(self, transport, now):
        item = next((row for row in self.items.values() if row["status"] == "pending"), None)
        if item:
            item["status"] = "claimed"
            return deepcopy(item)
        return None

    def begin(self, item_id, token, now, authorized):
        item = next(row for row in self.items.values() if row["id"] == item_id)
        item["status"] = "sending" if authorized else "cancelled"
        return deepcopy(item) if authorized else None

    def finish(self, item_id, token, outcome, provider_id, now):
        self.outcomes.append(outcome)
        item = next(row for row in self.items.values() if row["id"] == item_id)
        item["status"] = outcome


def test_preview_is_read_only_and_repeat_mock_cycles_send_once():
    store, tasks, members = Store(), Tasks(), Members()
    now = at("2026-11-17T14:00:00+00:00")
    assert scan_reminders(store, tasks, members, settings(), now)["eligible"] == 1
    assert not store.items
    first = next_reminder(store, tasks, members, settings(), clock=lambda: now)
    second = next_reminder(store, tasks, members, settings(), clock=lambda: now)
    assert first["delivery"] is None and first["mock_processed"] == 1
    assert second["mock_processed"] == 0
    assert store.outcomes == ["mock_sent"]
    assert len(store.items) == 1


def test_unknown_shared_assignment_does_not_guess_a_recipient():
    store = Store()
    report = scan_reminders(store, Tasks([task(assignee_text="Demo One Unknown Person")]),
                            Members(), settings(), at("2026-11-17T14:00:00+00:00"), write=True)
    assert report["unresolved_assignments"] == 1
    assert not store.items


def test_photon_payload_is_authorized_once_and_contains_the_task_code():
    store, tasks, members = Store(), Tasks(), Members()
    now = at("2026-11-17T14:00:00+00:00")
    result = next_reminder(store, tasks, members, settings(reminder_transport="photon"), clock=lambda: now)
    assert result["delivery"]["recipient"] == "+15555550123"
    assert "WIN-202610-1" in result["delivery"]["text"]
    assert not next_reminder(store, tasks, members, settings(reminder_transport="photon"),
                             clock=lambda: now, scan=False)["delivery"]


def test_disabled_worker_does_not_touch_database():
    assert next_reminder(None, None, None, settings(reminders_enabled=False)) == {
        "enabled": False, "delivery": None,
    }


def test_assignment_is_checked_again_after_claim():
    store, tasks = Store(), Tasks()
    now = at("2026-11-17T14:00:00+00:00")
    scan_reminders(store, tasks, Members(), settings(), now, write=True)
    tasks.rows[0]["assignee_text"] = "Other Person"
    result = next_reminder(store, tasks, Members(), settings(), clock=lambda: now, scan=False)
    assert result["delivery"] is None
    assert next(iter(store.items.values()))["status"] == "cancelled"


def test_old_seven_day_queue_cannot_send_during_the_new_help_window():
    store, tasks, members = Store(), Tasks(), Members()
    scan_reminders(store, tasks, members, settings(), at("2026-11-13T14:00:00+00:00"), write=True)
    config = settings(reminder_transport="photon")
    now = at("2026-11-15T14:00:00+00:00")
    assert next_reminder(store, tasks, members, config, clock=lambda: now, scan=False)["delivery"] is None
    assert next(iter(store.items.values()))["status"] == "cancelled"
    text = next_reminder(store, tasks, members, config, clock=lambda: now)["delivery"]["text"]
    assert "suggestions" in text and "help WIN-202610-1" in text and "admin approval" in text


def test_internal_routes_require_bridge_auth_even_when_disabled(monkeypatch):
    monkeypatch.setenv("WINNIE_MESSAGING_BRIDGE_SECRET", "test-secret")
    monkeypatch.setenv("WINNIE_REMINDERS_ENABLED", "false")
    with TestClient(app) as client:
        assert client.post("/api/internal/reminders/next", json={}).status_code == 401
        response = client.post("/api/internal/reminders/next", json={}, headers={
            "X-Winnie-Bridge-Secret": "test-secret",
        })
        assert response.status_code == 200
        assert response.json() == {"enabled": False, "delivery": None}


def test_sent_ack_needs_provider_confirmation(monkeypatch):
    monkeypatch.setenv("WINNIE_MESSAGING_BRIDGE_SECRET", "test-secret")
    with TestClient(app) as client:
        response = client.post("/api/internal/reminders/result", headers={
            "X-Winnie-Bridge-Secret": "test-secret",
        }, json={
            "delivery_id": "11111111-1111-4111-8111-111111111111",
            "claim_token": "22222222-2222-4222-8222-222222222222", "outcome": "sent",
        })
        assert response.status_code == 422
