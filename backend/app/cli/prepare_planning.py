"""Build private planning context from calendar and monthly tracker CSVs; no writes to Google."""

import argparse
import csv
import io
import json
from pathlib import Path

from app.services.planning_context import build_knowledge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calendar", type=Path)
    parser.add_argument("tracker", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--tab", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = list(csv.reader(io.StringIO(args.tracker.read_text(encoding="utf-8-sig"))))
    header_index = next(i for i, row in enumerate(rows) if "Task Name" in row and "Event" in row)
    header = rows[header_index]
    indices = [header.index(name) for name in ("Event", "Task Name", "Deadline", "Winnie Task ID")]
    sanitized = [[row[i] if i < len(row) else "" for i in indices] for row in rows]
    if "Assignee" in header:
        assignee_index = header.index("Assignee")
        for original, sanitized_row in zip(rows, sanitized):
            sanitized_row.append(original[assignee_index] if assignee_index < len(original) else "")
    knowledge = build_knowledge(args.calendar.read_text(encoding="utf-8-sig"), sanitized,
                                year=args.year, spreadsheet_id=args.spreadsheet_id, tab_name=args.tab)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(knowledge, output, indent=2)
    print(json.dumps({"calendar_events": len(knowledge["events"]),
                      "matched_events": sum(bool(event["tasks"]) for event in knowledge["events"]),
                      "unmatched_tracker_groups": knowledge["unmatched_tracker_groups"]}))


if __name__ == "__main__":
    main()
