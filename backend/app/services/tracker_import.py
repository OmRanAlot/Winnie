"""Read-only normalization of tracker exports. No database or Google account access.

Monthly tabs are snapshots of a semester tracker, not independent sets of tasks.
Missing permanent IDs are reported; titles and row positions are never used as IDs.
"""

import csv
import io
import re
from collections import Counter
from datetime import datetime

from pydantic import BaseModel, ValidationError

from app.schemas.tasks import MonthCode, SemesterCode, SourceId, TaskCreate

MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
STATUS_MAP = {
    "completed": "done", "in progress": "in_progress",
    "upcoming": "todo", "blocked": "blocked",
}


class TrackerContext(BaseModel):
    semester_code: SemesterCode
    spreadsheet_id: SourceId
    tab_name: str
    tab_id: SourceId | None = None
    project_name: str | None = None
    # Only required for a non-monthly tab; this groups the legacy generated task code.
    initial_month: MonthCode | None = None


def snapshot_context(tab_name: str) -> tuple[bool, str | None]:
    """An OLD prefix archives the snapshot; it says nothing about task completion."""
    name = tab_name.strip()
    archived = bool(re.match(r"^old\b", name, re.IGNORECASE))
    name = re.sub(r"^old\s+", "", name, flags=re.IGNORECASE)
    match = re.fullmatch(r"([A-Za-z]+)\s+([0-9]{4})", name)
    if match and match[1].lower() in MONTHS:
        month = MONTHS.index(match[1].lower()) + 1
        return archived, f"{match[2]}-{month:02d}"
    return archived, None


def parse_deadline(value: str) -> tuple[str | None, str | None]:
    """Keep exact source years; never constrain deadlines to the source semester."""
    if value.lower() in ("", "as needed", "tbd", "n/a"):
        return None, "deadline_not_fixed"
    # Two-digit years are explicitly interpreted as 2000..2099 for these trackers.
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", value):
        value = value[:-2] + "20" + value[-2:]
    for date_format in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date().isoformat(), None
        except ValueError:
            pass
    return None, "unrecognized_deadline"


def preview_tracker(text: str, context: TrackerContext) -> dict:
    """Return proposed rows and review issues without changing any source or database."""
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise ValueError("Tracker export is empty.")
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",\t").delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in text.splitlines()[0] else ","
    # Only sniff the separator. A sample without escaped quotes can incorrectly
    # infer doublequote=False and corrupt later notes containing commas/quotes.
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    header_index = next((
        i for i, row in enumerate(rows)
        if "task name" in [cell.strip().lower() for cell in row]
        and "deadline" in [cell.strip().lower() for cell in row]
    ), None)
    if header_index is None:
        raise ValueError("Expected a header row containing Task Name and Deadline.")
    header = [cell.strip().lower() for cell in rows[header_index]]
    columns = {name: i for i, name in enumerate(header)}
    notices = []
    # GirlHacks exports have two Priority labels; column five actually contains assignees.
    if "assignee" not in columns and header.count("priority") == 2 and "category" in columns:
        positions = [i for i, name in enumerate(header) if name == "priority"]
        columns["priority"], columns["assignee"] = positions
        notices.append("Second Priority column interpreted as Assignee; source preserved.")
    elif len(header) != len(set(header)):
        raise ValueError("Duplicate headers require an explicit column mapping.")
    required = {"task name", "status", "priority", "assignee", "deadline", "notes"}
    if required - columns.keys() or not ({"event", "category"} & columns.keys()):
        raise ValueError("Tracker columns do not match the supported Event/Category layout.")

    archived, snapshot_month = snapshot_context(context.tab_name)
    initial_month = context.initial_month or snapshot_month
    if initial_month is None:
        raise ValueError("For a non-monthly tab, provide initial_month (YYYY-MM).")
    if "category" in columns and not context.project_name:
        raise ValueError("Provide project_name for a category tracker such as GirlHacks.")
    if archived:
        notices.append("Archived snapshot: excluded from current task updates and reminders.")

    proposals = []
    for row_number, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            proposals.append({
                "row": row_number, "task": None, "errors": ["column_count_mismatch"],
                "warnings": [], "ready_for_current_sync": False, "source_values": row,
            })
            continue

        def cell(name, row=row):
            return row[columns[name]].strip() if name in columns else ""

        errors, warnings = [], []
        task_id = cell("winnie task id") or None
        if task_id is None:
            errors.append("missing_winnie_task_id")
        status = STATUS_MAP.get(cell("status").lower())
        if status is None:
            errors.append("unrecognized_status")
        deadline, deadline_issue = parse_deadline(cell("deadline"))
        if deadline_issue == "unrecognized_deadline":
            errors.append(deadline_issue)
        elif deadline_issue:
            warnings.append(deadline_issue)
        if not cell("assignee"):
            warnings.append("missing_assignee")
        task = {
            "title": cell("task name"), "description": cell("notes"),
            "month_code": initial_month, "semester_code": context.semester_code,
            "snapshot_month": snapshot_month, "status": status,
            "priority": cell("priority").lower(), "assignee_text": cell("assignee"),
            "deadline_text": cell("deadline"), "due_date": deadline,
            "event_tag": cell("event") or None,
            "category": cell("category") or None, "project_name": context.project_name,
            "source": "sheet", "source_spreadsheet_id": context.spreadsheet_id,
            "source_task_id": task_id, "source_tab_id": context.tab_id,
            "source_tab_name": context.tab_name,
        }
        try:
            task = TaskCreate.model_validate(task).model_dump(mode="json")
        except ValidationError as exc:
            # Report field names only, never echo sensitive values through validation messages.
            errors.extend(f"invalid_{'.'.join(map(str, error['loc']))}" for error in exc.errors())
            task = None
        proposals.append({
            "row": row_number, "task": task, "errors": errors, "warnings": warnings,
            "source_values": row,
            "ready_for_current_sync": not archived and not errors,
        })

    ids = Counter(
        proposal["task"]["source_task_id"] for proposal in proposals
        if proposal["task"] and proposal["task"]["source_task_id"]
    )
    for proposal in proposals:
        if proposal["task"] and ids[proposal["task"]["source_task_id"]] > 1:
            proposal["errors"].append("duplicate_winnie_task_id")
            proposal["ready_for_current_sync"] = False
    return {
        "mode": "preview_only", "database_writes": 0,
        "semester_code": context.semester_code, "archived": archived,
        "snapshot_month": snapshot_month, "notices": notices,
        "summary": {
            "rows": len(proposals),
            "ready_for_current_sync": sum(p["ready_for_current_sync"] for p in proposals),
            "rows_with_errors": sum(bool(p["errors"]) for p in proposals),
            "errors": dict(Counter(error for p in proposals for error in p["errors"])),
            "warnings": dict(Counter(warning for p in proposals for warning in p["warnings"])),
        },
        "rows": proposals,
    }
