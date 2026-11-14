"""Run with: uv run python -m app.cli.preview_tracker --help (from backend/)."""

import argparse
import json
from pathlib import Path

from app.services.tracker_import import TrackerContext, preview_tracker


def main():
    parser = argparse.ArgumentParser(description="Preview a tracker CSV/TSV; never writes tasks.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--semester", required=True, help="For example spring-2026")
    parser.add_argument("--spreadsheet-id", required=True, help="Stable sheet ID, not a tab name")
    parser.add_argument("--tab", required=True, help="For example April 2026 or OLD March 2026")
    parser.add_argument("--tab-id", help="Google Sheets gid, if known; survives a tab rename")
    parser.add_argument("--project", help="For example GirlHacks 2026")
    parser.add_argument("--initial-month", help="Legacy task-code group for non-monthly tabs")
    parser.add_argument("--output", type=Path, help="Optional private JSON report; may contain PII")
    args = parser.parse_args()
    try:
        context = TrackerContext(
            semester_code=args.semester, spreadsheet_id=args.spreadsheet_id,
            tab_name=args.tab, tab_id=args.tab_id, project_name=args.project,
            initial_month=args.initial_month,
        )
        report = preview_tracker(args.file.read_text(encoding="utf-8-sig"), context)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Preview failed: {exc}\n")
    if args.output:
        if args.output.resolve() == args.file.resolve():
            parser.error("Output must not overwrite the source export.")
        if args.output.exists():
            parser.error("Output already exists; choose a new report filename.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=False)
    # Terminal summary deliberately excludes names, emails, task bodies and deadlines.
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
