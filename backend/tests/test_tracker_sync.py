"""Exercise import decisions and retries without using a real Supabase account."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.integrations.supabase import StorageUnavailable
from app.services.tasks import TaskStore
from app.services.tracker_import import TrackerContext, preview_tracker
from app.services.tracker_sync import (
    ImportConflict,
    ImportInterrupted,
    apply_import,
    plan_import,
)

TARGET = "https://demo.supabase.co"
CSV = (
    "Event,Task Name,Status,Priority,Assignee,Deadline,Notes,Winnie Task ID\n"
    "Workshop,Book room,Upcoming,High,Demo member,4/20/2026,,SPR26-001\n"
)


def preview(text=CSV, **context):
    return preview_tracker(text, TrackerContext(**{
        "semester_code": "spring-2026", "spreadsheet_id": "demo-sheet",
        "tab_name": "April 2026", **context,
    }))


class MemoryStore:
    def __init__(self):
        self.tasks = []
        self.revision = 0

    def tracker_tasks(self, spreadsheet_id):
        return deepcopy([
            task for task in self.tasks if task["source_spreadsheet_id"] == spreadsheet_id
        ])

    def insert_import_task(self, task):
        key = (task["source_spreadsheet_id"], task["source_task_id"])
        if any((t["source_spreadsheet_id"], t["source_task_id"]) == key for t in self.tasks):
            raise StorageUnavailable("Unique index conflict")
        self.revision += 1
        stored = {
            **deepcopy(task), "id": str(uuid4()), "task_code": f"WIN-{self.revision}",
            "updated_at": str(self.revision),
        }
        self.tasks.append(stored)
        return [deepcopy(stored)]

    def update_import_task(self, task_id, expected_updated_at, changes):
        for task in self.tasks:
            if task["id"] == task_id and task["updated_at"] == expected_updated_at:
                self.revision += 1
                task.update(deepcopy(changes), updated_at=str(self.revision))
                return [deepcopy(task)]
        return []


def test_first_import_then_repeat_does_not_duplicate():
    store = MemoryStore()
    plan = plan_import(preview(), store, TARGET)
    assert plan["summary"] == {"insert": 1, "update": 0, "unchanged": 0}
    assert store.tasks == []  # Planning is read-only.
    assert apply_import(plan, store, plan["plan_id"])["completed"]["insert"] == 1
    repeat = plan_import(preview(), store, TARGET)
    assert repeat["summary"] == {"insert": 0, "update": 0, "unchanged": 1}
    assert apply_import(repeat, store, repeat["plan_id"])["write_requests"] == 0
    assert len(store.tasks) == 1


def test_new_month_updates_same_task_and_preserves_internal_fields():
    store = MemoryStore()
    first = plan_import(preview(), store, TARGET)
    apply_import(first, store, first["plan_id"])
    store.tasks[0].update(owner_code="DEMO", stakeholder_codes=["DEMO"], tags=["keep"])
    original = deepcopy(store.tasks[0])
    updated = CSV.replace("Upcoming", "Completed").replace("4/20/2026", "5/2/2026")
    plan = plan_import(preview(updated, tab_name="May 2026"), store, TARGET)
    assert plan["operations"][0]["before"]["status"] == "todo"
    apply_import(plan, store, plan["plan_id"])
    saved = store.tasks[0]
    for field in ("id", "task_code", "month_code", "owner_code", "stakeholder_codes", "tags"):
        assert saved[field] == original[field]
    assert saved["status"] == "done"
    assert saved["snapshot_month"] == "2026-05"
    assert saved["due_date"] == "2026-05-02"


def test_archive_and_invalid_rows_never_read_storage():
    class NoReads:
        def tracker_tasks(self, spreadsheet_id):
            pytest.fail("Invalid input should not reach storage")

    with pytest.raises(ImportConflict, match="OLD"):
        plan_import(preview(tab_name="OLD April 2026"), NoReads(), TARGET)
    with pytest.raises(ImportConflict, match="errors"):
        plan_import(preview(CSV.replace("SPR26-001", "")), NoReads(), TARGET)


def test_older_month_cannot_insert_unknown_tasks_or_overwrite_newer_ones():
    store = MemoryStore()
    plan = plan_import(preview(tab_name="May 2026"), store, TARGET)
    apply_import(plan, store, plan["plan_id"])
    with pytest.raises(ImportConflict, match="later snapshot"):
        plan_import(preview(CSV.replace("SPR26-001", "SPR26-002")), store, TARGET)


def test_same_id_in_another_spreadsheet_is_a_different_task():
    store = MemoryStore()
    plan = plan_import(preview(), store, TARGET)
    apply_import(plan, store, plan["plan_id"])
    other = plan_import(preview(spreadsheet_id="other-sheet"), store, TARGET)
    assert other["summary"]["insert"] == 1


def test_semester_mismatch_is_not_silently_reassigned():
    store = MemoryStore()
    first = plan_import(preview(), store, TARGET)
    apply_import(first, store, first["plan_id"])
    with pytest.raises(ImportConflict, match="semester"):
        plan_import(preview(semester_code="fall-2026"), store, TARGET)


def test_confirmation_binds_database_input_and_stored_revision():
    store = MemoryStore()
    first = plan_import(preview(), store, TARGET)
    for changed in (
        plan_import(preview(), store, "https://other.supabase.co"),
        plan_import(preview(CSV.replace("Book room", "Book hall")), store, TARGET),
    ):
        with pytest.raises(ImportConflict, match="plan changed"):
            apply_import(changed, store, first["plan_id"])
    assert not store.tasks
    apply_import(first, store, first["plan_id"])
    before = plan_import(preview(CSV.replace("Upcoming", "Completed")), store, TARGET)
    store.tasks[0]["updated_at"] = "external-change"
    after = plan_import(preview(CSV.replace("Upcoming", "Completed")), store, TARGET)
    with pytest.raises(ImportConflict, match="plan changed"):
        apply_import(after, store, before["plan_id"])


def test_concurrent_change_after_planning_stops_without_overwriting():
    store = MemoryStore()
    first = plan_import(preview(), store, TARGET)
    apply_import(first, store, first["plan_id"])
    plan = plan_import(preview(CSV.replace("Upcoming", "Completed")), store, TARGET)
    store.tasks[0]["updated_at"] = "external-change"
    with pytest.raises(ImportInterrupted) as exc:
        apply_import(plan, store, plan["plan_id"])
    assert exc.value.completed["update"] == 0
    assert store.tasks[0]["status"] == "todo"


def test_unknown_write_outcome_can_be_retried_without_duplicates():
    class TimeoutAfterSave(MemoryStore):
        fail_once = True

        def insert_import_task(self, task):
            saved = super().insert_import_task(task)
            if self.fail_once:
                self.fail_once = False
                raise StorageUnavailable("Connection lost after commit")
            return saved

    store = TimeoutAfterSave()
    plan = plan_import(preview(), store, TARGET)
    with pytest.raises(ImportInterrupted) as exc:
        apply_import(plan, store, plan["plan_id"])
    assert exc.value.attempted == 1
    assert len(store.tasks) == 1
    retry = plan_import(preview(), store, TARGET)
    assert apply_import(retry, store, retry["plan_id"])["write_requests"] == 0
    assert len(store.tasks) == 1


def test_absent_tasks_are_not_deleted_or_marked_done():
    store = MemoryStore()
    first = plan_import(preview(), store, TARGET)
    apply_import(first, store, first["plan_id"])
    new = plan_import(preview(CSV.replace("SPR26-001", "SPR26-002")), store, TARGET)
    apply_import(new, store, new["plan_id"])
    assert len(store.tasks) == 2
    assert store.tasks[0]["status"] == "todo"


def test_csv_without_tab_gid_does_not_clear_stored_gid():
    store = MemoryStore()
    first = plan_import(preview(tab_id="123"), store, TARGET)
    apply_import(first, store, first["plan_id"])
    assert plan_import(preview(), store, TARGET)["summary"]["unchanged"] == 1


def test_store_fetches_all_pages_and_guards_updates_by_revision():
    calls = []

    class Table:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                calls.append((name, args, kwargs))
                return self
            return method

    store = TaskStore()
    pages = iter([SimpleNamespace(data=[{}] * 500), SimpleNamespace(data=[{}])])

    def execute(operation):
        operation(Table())
        return next(pages)

    store._execute = execute
    assert len(store.tracker_tasks("demo-sheet")) == 501
    assert ("range", (500, 999), {}) in calls
    pages = iter([SimpleNamespace(data=[{}])])
    store.update_import_task("task-id", "revision", {"status": "done"})
    assert ("eq", ("updated_at", "revision"), {}) in calls


def test_cli_previews_then_applies_without_real_credentials(tmp_path, monkeypatch, capsys):
    import json
    import sys

    from app import import_tracker

    source = tmp_path / "tracker.csv"
    source.write_text(CSV, encoding="utf-8")
    store = MemoryStore()
    monkeypatch.setattr(import_tracker, "TaskStore", lambda: store)
    monkeypatch.setattr(import_tracker, "Settings", lambda: SimpleNamespace(supabase_url=TARGET))
    args = [
        "import_tracker", str(source), "--semester", "spring-2026",
        "--spreadsheet-id", "demo-sheet", "--tab", "April 2026",
    ]
    monkeypatch.setattr(sys, "argv", args)
    import_tracker.main()
    result = json.loads(capsys.readouterr().out)
    assert result["database_writes"] == 0
    assert not store.tasks
    monkeypatch.setattr(sys, "argv", [*args, "--apply", "--expect-plan", result["plan_id"]])
    import_tracker.main()
    assert json.loads(capsys.readouterr().out)["completed"]["insert"] == 1
    assert source.read_text(encoding="utf-8") == CSV
