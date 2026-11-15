"""Deadline schedules and a persistent outbox; all clocks are explicit and injectable."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.members import AliasConflict, assignment_members
from app.services.tasks import TaskNotFound


def utc_now():
    return datetime.now(UTC)


def instant(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("Reminder timestamps must include a timezone.")
    return value


def reminder_slots(task, now, *, timezone_name="America/New_York", daytime_hour=9, evening_hour=18):
    now = instant(now)
    if task["status"] == "done" or not task.get("due_date"):
        return []
    due = date.fromisoformat(task["due_date"])
    zone = ZoneInfo(timezone_name)
    basis = instant(task.get("reminder_schedule_started_at") or task["created_at"])
    schedule = [
        ("fourteen_day", datetime.combine(due - timedelta(days=14), time(daytime_hour), zone)),
        ("seven_day", datetime.combine(due - timedelta(days=7), time(daytime_hour), zone)),
        ("five_day_help", datetime.combine(due - timedelta(days=5), time(daytime_hour), zone)),
        ("three_day", datetime.combine(due - timedelta(days=3), time(daytime_hour), zone)),
        ("previous_evening", datetime.combine(due - timedelta(days=1), time(evening_hour), zone)),
    ]
    result = []
    for index, (kind, scheduled) in enumerate(schedule):
        expires = schedule[index + 1][1] if index + 1 < len(schedule) else datetime.combine(
            due, time(0), zone,
        )
        if basis <= scheduled <= now < expires:
            result.append({
                "kind": kind, "scheduled_at": scheduled.astimezone(UTC).isoformat(),
                "expires_at": expires.astimezone(UTC).isoformat(),
            })
    return result


def scan_reminders(store, tasks, members, settings, now, *, write=False):
    """A preview never writes. Only a currently eligible stage is queued; no catch-up burst."""
    recipients = {row["member_code"]: row for row in store.recipients()}
    aliases = members.aliases(settings.active_semester)
    summary = {"eligible": 0, "queued_or_refreshed": 0, "unresolved_assignments": 0}
    for task in tasks.unfinished_for_semester(settings.active_semester):
        slots = reminder_slots(
            task, now, timezone_name=settings.reminder_timezone,
            daytime_hour=settings.reminder_daytime_hour, evening_hour=settings.reminder_evening_hour,
        )
        if not slots:
            continue
        try:
            assigned = ({task["owner_code"]} if task.get("owner_code") else
                        assignment_members(task.get("assignee_text", ""), aliases))
        except AliasConflict:
            assigned = None
        if assigned is None:
            summary["unresolved_assignments"] += 1
            continue
        for code in sorted(assigned & recipients.keys()):
            recipient = recipients[code]
            for slot in slots:
                summary["eligible"] += 1
                if write:
                    event = f" for {task['event_tag']}" if task.get("event_tag") else ""
                    if slot["kind"] == "five_day_help":
                        body = (
                            f"Your deadline for {task['title']}{event} ({task['task_code']}) "
                            f"is getting close: {task['due_date']}. Now is a good time to ask for help. "
                            "Would you like suggestions for someone we could reach out to? "
                            f"Reply help {task['task_code']}. Transfers need admin approval."
                        )
                    else:
                        body = (
                            f"Deadline reminder: {task['title']}{event} ({task['task_code']}) "
                            f"is due {task['due_date']}. Reply done {task['task_code']} when finished."
                        )
                    if store.queue(task, recipient, slot, body, settings.reminder_transport, now):
                        summary["queued_or_refreshed"] += 1
    return summary


def next_reminder(store, tasks, members, settings, clock=utc_now, *, scan=True):
    if not settings.reminders_enabled:
        return {"enabled": False, "delivery": None}
    now = clock()
    summary = scan_reminders(store, tasks, members, settings, now, write=True) if scan else {}
    mock_processed = 0
    for _ in range(20):
        item = store.claim(settings.reminder_transport, clock())
        if item is None:
            break
        authorized = False
        try:
            task = tasks.get(item["task_id"])
            assigned = ({task["owner_code"]} if task.get("owner_code") else assignment_members(
                task.get("assignee_text", ""), members.aliases(settings.active_semester),
            ))
            authorized = (
                task.get("semester_code") == settings.active_semester
                and assigned is not None and item["member_code"] in assigned
                and any(slot["kind"] == item["kind"] for slot in reminder_slots(
                    task, clock(), timezone_name=settings.reminder_timezone,
                    daytime_hour=settings.reminder_daytime_hour, evening_hour=settings.reminder_evening_hour,
                ))
            )
        except (TaskNotFound, AliasConflict):
            pass
        delivery = store.begin(item["id"], item["claim_token"], clock(), authorized)
        if delivery is None:
            continue
        if delivery["transport"] == "mock":
            store.finish(delivery["id"], delivery["claim_token"], "mock_sent", None, clock())
            mock_processed += 1
            continue
        return {
            "enabled": True, "delivery": {
                "id": delivery["id"], "claim_token": delivery["claim_token"],
                "transport": "photon", "recipient": delivery["sender_id"], "text": delivery["body"],
            },
            "summary": summary,
        }
    return {"enabled": True, "delivery": None, "mock_processed": mock_processed, "summary": summary}
