"""Preview database changes by default. Saving requires --apply --expect-plan <hash>."""

import argparse
import json
from pathlib import Path

from app.integrations.supabase import StorageUnavailable
from app.services.tasks import TaskStore
from app.services.tracker_import import TrackerContext, preview_tracker
from app.services.tracker_sync import (
    ImportConflict,
    ImportInterrupted,
    apply_import,
    plan_import,
)
from app.settings import Settings


def main():
    parser = argparse.ArgumentParser(description="Preview or apply a tracker import to Supabase.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--semester", required=True)
    parser.add_argument("--spreadsheet-id", required=True, help="Use the real stable sheet ID")
    parser.add_argument("--tab", required=True)
    parser.add_argument("--tab-id")
    parser.add_argument("--project")
    parser.add_argument("--initial-month")
    parser.add_argument("--output", type=Path, help="Optional private JSON plan with before/after values")
    parser.add_argument("--apply", action="store_true", help="Save the reviewed changes")
    parser.add_argument("--expect-plan", help="plan_id printed by the previous database preview")
    args = parser.parse_args()
    if args.apply and not args.expect_plan:
        parser.error("Run a preview first, then supply --apply --expect-plan <plan_id>.")
    if args.expect_plan and not args.apply:
        parser.error("--expect-plan is used with --apply.")
    if args.output and (args.output.resolve() == args.file.resolve() or args.output.exists()):
        parser.error("Choose a new output path; do not overwrite the source or an existing report.")
    try:
        context = TrackerContext(
            semester_code=args.semester, spreadsheet_id=args.spreadsheet_id,
            tab_name=args.tab, tab_id=args.tab_id, project_name=args.project,
            initial_month=args.initial_month,
        )
        preview = preview_tracker(args.file.read_text(encoding="utf-8-sig"), context)
        settings = Settings()
        store = TaskStore()
        plan = plan_import(preview, store, settings.supabase_url)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(plan, output, indent=2, ensure_ascii=False)
        result = {
            "mode": "database_preview", "database_writes": 0,
            "plan_id": plan["plan_id"], "summary": plan["summary"],
            "warnings": plan["warnings"],
            "status_changes": [
                {"task_id": op["source_task_id"], "before": op["before"]["status"],
                 "after": op["values"]["status"]}
                for op in plan["operations"]
                if op["action"] == "update" and "status" in op["values"]
            ],
        }
        if args.apply:
            result = apply_import(plan, store, args.expect_plan)
    except ImportInterrupted as exc:
        print(json.dumps({
            "mode": "interrupted", "completed": exc.completed,
            "write_requests_attempted": exc.attempted,
            "message": "Some writes may have succeeded. Preview again before retrying.",
        }, indent=2))
        parser.exit(1)
    except StorageUnavailable:
        parser.exit(1, "Task storage unavailable. Check Supabase settings, migrations and access.\n")
    except (ImportConflict, ValueError, OSError) as exc:
        parser.exit(2, f"Import stopped: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
