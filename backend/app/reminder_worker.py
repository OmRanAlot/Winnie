"""Preview reminder eligibility, or run a mock dispatch cycle. No real sends from this CLI."""

import argparse
import json

from app.core.settings import Settings
from app.integrations.reminders import ReminderStore
from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore
from app.services.reminders import instant, next_reminder, scan_reminders, utc_now
from app.services.tasks import TaskStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Queue and record mock sends only")
    mode.add_argument("--status", action="store_true", help="Show persistent delivery status counts")
    parser.add_argument("--at", help="Inject an ISO timestamp for mock demos; never for real delivery")
    args = parser.parse_args()
    settings = Settings()
    if args.at and settings.reminder_transport != "mock":
        parser.error("A demo clock is only permitted with reminder transport mock.")
    if args.once and settings.reminder_transport != "mock":
        parser.error("This CLI dispatches mock reminders only; real sends use the Photon listener.")
    try:
        now = instant(args.at) if args.at else utc_now()
    except ValueError:
        parser.error("--at requires an ISO timestamp with a timezone, such as 2027-01-13T14:00:00Z.")
    store, tasks, members = ReminderStore(), TaskStore(), MemberStore()
    try:
        if args.status:
            result = {"statuses": store.statuses()}
        elif args.once:
            result = next_reminder(store, tasks, members, settings.model_copy(update={
                "reminders_enabled": True,
            }), clock=lambda: now)
        else:
            result = scan_reminders(store, tasks, members, settings, now, write=False)
            result.update(mode="preview", database_writes=0)
        result["clock"] = "demo" if args.at else "real"
        print(json.dumps(result, indent=2))
    except (StorageUnavailable, ValueError, KeyError):
        parser.exit(1, "Reminder operation failed. Check settings, migration and timezone.\n")


if __name__ == "__main__":
    main()
