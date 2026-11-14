"""Read-only history. Attendance is excluded; owner text stays in private local context."""

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

from app.planning_schemas import PlanningRequest

# Reviewed aliases from the Fall calendar and October tracker; never fuzzy-join silently.
ALIASES = {
    "involvement fair": "student involvement fair",
    "wics tech workshop 1": "wics technical workshop",
    "verizon event": "verizon info session",
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def event_format(name: str) -> str:
    name = normalize(name)
    if re.search(r"\bgbm\b", name):
        return "gbm"
    if "technical workshop" in name:
        return "technical_workshop"
    if "girlhacks" in name:
        return "hackathon"
    return "other"


def build_knowledge(calendar_text: str, tracker_rows: list[list[str]], *, year: int,
                    spreadsheet_id: str, tab_name: str) -> dict:
    """Join task groups to explicitly named calendar events, preserving source rows."""
    events = []
    for row_number, row in enumerate(csv.DictReader(io.StringIO(calendar_text.lstrip('\ufeff'))), 2):
        name = (row.get("Event") or "").strip()
        raw_date = (row.get("Date") or "").strip()
        match = re.match(r"(\d{1,2})/(\d{1,2})", raw_date)
        if not name or not match:
            continue
        start = date(year, int(match[1]), int(match[2]))
        events.append({
            "name": name, "event_type": (row.get("Event Type") or "").strip() or None,
            "event_format": event_format(name), "start_date": start.isoformat(),
            "date_text": raw_date, "calendar_row": row_number, "tasks": [],
        })
    by_name = {normalize(event["name"]): event for event in events}
    unmatched = set()
    # Sanitized columns: Event, Task Name, Deadline, Winnie Task ID.
    for row_number, row in enumerate(tracker_rows, 1):
        if len(row) < 4 or not row[1].strip() or row[1].strip() == "Task Name":
            continue
        key = normalize(row[0])
        event = by_name.get(ALIASES.get(key, key))
        if event is None:
            if row[0] and row_number > 2:
                unmatched.add(row[0])
            continue
        event["tasks"].append({
            "title": row[1].strip(), "historical_deadline": row[2].strip(),
            "evidence_id": f"october-row-{row_number}",
            "source_task_id": row[3].strip() or None,
            "source_range": f"'{tab_name}'!A{row_number}:H{row_number}",
            "source_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
            "historical_assignee_text": row[4].strip() if len(row) > 4 else "",
        })
    return {"schema_version": 1, "year": year, "tab_name": tab_name,
            "events": events, "unmatched_tracker_groups": sorted(unmatched)}


def load_examples(path: Path, request: PlanningRequest) -> tuple[list[dict], list[str]]:
    knowledge = json.loads(path.read_text(encoding="utf-8"))
    if knowledge.get("schema_version") != 1:
        raise ValueError("Unsupported planning knowledge version.")
    for event in knowledge["events"]:
        for task in event["tasks"]:
            task.pop("historical_assignee_text", None)
    kind = request.event_format
    if kind == "other":
        kind = event_format(request.event_name + " " + request.idea)
    events = [event for event in knowledge["events"]
              if event["event_type"] == request.event_type
              and (request.event_type != "WiCS" or event["event_format"] == kind)]
    examples = [event for event in events if event["tasks"]][:4]
    warnings = [
        "Historical examples are incomplete; missing tasks are not evidence they are unnecessary.",
        "Historical completion status and attendance do not imply current commitments.",
        "Roles, dependencies and dates are suggestions requiring review; no people are assigned.",
    ]
    if not examples:
        warnings.append("No matching task history for this event type/format; gather requirements.")
    if any(not event["tasks"] for event in events):
        warnings.append("Some matching calendar events have no tasks in the October snapshot.")
    return examples, warnings
