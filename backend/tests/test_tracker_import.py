"""Synthetic examples only: never commit private tracker exports or member details."""

import csv
import io

import pytest
from pydantic import ValidationError

from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services.tracker_import import TrackerContext, preview_tracker

HEADERS = [
    "Event", "Task Name", "Status", "Priority", "Assignee", "Deadline", "Notes",
    "Winnie Task ID",
]
ROW = ["Workshop", "Book room", "Upcoming", "High", "Member A Member B", "04/20/26", "", "S26-1"]


def export(rows, headers=HEADERS, delimiter=","):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter)
    writer.writerow(["Tracker title"] + [""] * (len(headers) - 1))
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def context(**changes):
    return TrackerContext(**{
        "semester_code": "spring-2026", "spreadsheet_id": "demo-sheet",
        "tab_name": "April 2026", **changes,
    })


def test_month_snapshot_is_separate_from_deadline_and_semester():
    row = ROW.copy()
    row[5] = "12/25/2025"
    report = preview_tracker(export([row]), context())
    task = report["rows"][0]["task"]
    assert task["due_date"] == "2025-12-25"
    assert task["snapshot_month"] == "2026-04"
    assert task["semester_code"] == "spring-2026"
    assert task["assignee_text"] == "Member A Member B"
    assert task["owner_code"] is None
    assert report["summary"]["ready_for_current_sync"] == 1
    assert report["database_writes"] == 0


def test_archive_preserves_status_and_cannot_update_current_tasks():
    report = preview_tracker(export([ROW]), context(tab_name="OLD March 2026"))
    assert report["archived"]
    assert report["snapshot_month"] == "2026-03"
    assert report["rows"][0]["task"]["status"] == "todo"
    assert report["summary"]["ready_for_current_sync"] == 0


def test_identity_survives_renaming_sorting_and_task_changes():
    old = preview_tracker(export([ROW]), context(tab_name="March 2026"))["rows"][0]["task"]
    revised = ROW.copy()
    revised[1:3] = ["Book a different room", "Completed"]
    revised[5] = "5/1/2026"
    another = ROW.copy()
    another[-1] = "S26-2"
    report = preview_tracker(export([another, revised]), context())
    new = report["rows"][1]["task"]
    for field in ("source_spreadsheet_id", "source_task_id"):
        assert old[field] == new[field]
    assert new["status"] == "done"
    assert new["due_date"] == "2026-05-01"


def test_missing_and_duplicate_ids_require_review():
    missing = ROW.copy()
    missing[-1] = ""
    report = preview_tracker(export([ROW, ROW, missing]), context())
    assert report["summary"]["ready_for_current_sync"] == 0
    assert report["summary"]["errors"] == {
        "duplicate_winnie_task_id": 2, "missing_winnie_task_id": 1,
    }


def test_original_exports_without_id_column_are_previewable_but_not_ready():
    report = preview_tracker(export([ROW[:-1]], HEADERS[:-1]), context())
    assert report["rows"][0]["task"]["source_task_id"] is None
    assert report["rows"][0]["errors"] == ["missing_winnie_task_id"]


def test_girlhacks_duplicate_header_and_non_date_deadline():
    headers = ["Category", *HEADERS[1:4], "Priority", *HEADERS[5:]]
    row = ROW.copy()
    row[0], row[5] = "Logistics", "As needed"
    report = preview_tracker(export([row], headers), context(
        tab_name="GirlHacks", project_name="GirlHacks 2026", initial_month="2026-11",
    ))
    task = report["rows"][0]["task"]
    assert task["category"] == "Logistics"
    assert task["project_name"] == "GirlHacks 2026"
    assert task["event_tag"] is None
    assert task["priority"] == "high"
    assert task["assignee_text"] == "Member A Member B"
    assert task["due_date"] is None
    assert task["deadline_text"] == "As needed"
    assert task["snapshot_month"] is None
    assert "deadline_not_fixed" in report["rows"][0]["warnings"]
    assert report["notices"]


@pytest.mark.parametrize("deadline", ["2/30/2026", "tomorrow"])
def test_uncertain_or_invalid_deadline_blocks_sync(deadline):
    row = ROW.copy()
    row[5] = deadline
    report = preview_tracker(export([row]), context())
    assert report["rows"][0]["errors"] == ["unrecognized_deadline"]
    assert report["rows"][0]["task"]["deadline_text"] == deadline
    assert not report["rows"][0]["ready_for_current_sync"]


@pytest.mark.parametrize("status,expected", [
    ("Completed", "done"), ("Upcoming", "todo"),
    ("In Progress", "in_progress"), ("Blocked", "blocked"),
])
def test_status_mapping(status, expected):
    row = ROW.copy()
    row[2] = status
    assert preview_tracker(export([row]), context())["rows"][0]["task"]["status"] == expected


def test_unknown_status_and_invalid_priority_do_not_get_silent_defaults():
    row = ROW.copy()
    row[2:4] = ["Cancelled", "Urgent"]
    proposal = preview_tracker(export([row]), context())["rows"][0]
    assert proposal["task"] is None
    assert {"unrecognized_status", "invalid_priority"} <= set(proposal["errors"])
    assert proposal["source_values"] == row


def test_tsv_quoted_multiline_notes_and_blank_lines():
    row = ROW.copy()
    row[6] = "Bring signs, pens\nand paper"
    report = preview_tracker(export([row, [""] * 8], delimiter="\t"), context())
    assert report["summary"]["rows"] == 1
    assert report["rows"][0]["task"]["description"] == row[6]


def test_escaped_quotes_after_dialect_sample_are_preserved():
    rows = []
    for i in range(100):
        row = ROW.copy()
        row[-1] = f"S26-{i}"
        row[6] = "Plain note " * 10
        rows.append(row)
    rows[-1][6] = 'Ask about "room A", then confirm'
    report = preview_tracker(export(rows), context())
    assert report["summary"]["rows"] == 100
    assert report["summary"]["rows_with_errors"] == 0
    assert report["rows"][-1]["task"]["description"] == rows[-1][6]


def test_empty_export_and_nonmonthly_tab_need_explicit_context():
    with pytest.raises(ValueError, match="empty"):
        preview_tracker("", context())
    with pytest.raises(ValueError, match="initial_month"):
        preview_tracker(export([ROW]), context(tab_name="GirlHacks"))


def test_existing_api_payload_still_valid_and_nonnullable_updates_rejected():
    task = TaskCreate(title="Manual test", month_code="2026-11")
    assert task.priority == "normal"
    assert task.semester_code is None
    with pytest.raises(ValidationError):
        TaskUpdate(priority=None)
    with pytest.raises(ValidationError):
        TaskCreate(title="Test", month_code="2026-11", source_task_id="orphan")
