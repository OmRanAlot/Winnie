"""Seed Supabase with a sample meeting and three extracted tasks, then print list_tasks().

Run from backend/ after applying supabase/migrations/0001_init.sql and setting SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY in .env:

    uv run python -m scripts.seed_example            # skips if the sample meeting exists
    uv run python -m scripts.seed_example --force    # inserts another copy anyway

Also creates one seat per key in data/eboardMembers.json (if present) so seat names match the
roster that task assignment uses. Only the seat keys are read, never phone numbers or emails.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.core.deadlines import NEW_YORK
from app.db import repository
from app.domain.models import ExtractedTask
from app.integrations.supabase_client import get_client

ROSTER = Path(__file__).resolve().parents[1] / "data" / "eboardMembers.json"
MEETING_TITLE = "Sample e-board sync (seed)"
MEETING_AT = datetime(2026, 11, 13, 18, 0, tzinfo=NEW_YORK)  # Friday 6 pm

EXAMPLE_TASKS = [
    ExtractedTask(
        title="Check alternate room booking",
        description="Ask the booking office for an alternate room for the Nov 24 career workshop "
        "and post the confirmation in the board chat.",
        seat="Vice President",
        assignee="Bob Newman",
        rationale="Bob agreed to handle the room booking.",
        deadline="by Monday noon",
        needs_review=False,
    ),
    ExtractedTask(
        title="Fix shared calendar and minutes",
        description="Change the workshop date to Tuesday Nov 24 at 6 pm in the calendar and minutes.",
        seat="Secretary",
        assignee="Alice",
        rationale="Alice copied the old agenda and offered to fix it.",
        deadline="tonight",
        needs_review=False,
    ),
    ExtractedTask(
        title="Get speaker details from company contact",
        description="Follow up for the speaker's name, title, short bio and A/V needs.",
        seat="Industry Partnership",
        assignee="Boba",
        rationale="Boba owns the company relationship.",
        deadline="Monday morning",
        needs_review=False,
    ),
]


def seed_roster_seats() -> int:
    if not ROSTER.exists():
        return 0
    seats = list(json.loads(ROSTER.read_text(encoding="utf-8")))
    for seat in seats:
        repository.get_or_create_seat(seat)
    return len(seats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Supabase with sample tasks.")
    parser.add_argument("--force", action="store_true", help="insert even if already seeded")
    args = parser.parse_args(argv)

    existing = get_client().table("meetings").select("id").eq("title", MEETING_TITLE).execute().data
    if existing and not args.force:
        print(f"Already seeded (meeting id {existing[0]['id']}). Use --force to add another copy.")
    else:
        print(f"Seats from roster: {seed_roster_seats()}")
        meeting_id = repository.create_meeting(MEETING_AT, MEETING_TITLE, None)
        stored = repository.insert_extracted_tasks(meeting_id, EXAMPLE_TASKS)
        print(f"Inserted meeting {meeting_id} with {len(stored)} tasks.")

    print("\nlist_tasks():")
    for task in repository.list_tasks():
        due = task.deadline_at.isoformat() if task.deadline_at else "unscheduled"
        print(
            f"  #{task.id} [{task.status}] {task.title} - {task.assignee or 'Unassigned'} "
            f"({task.seat or '-'}) due {due} (said: {task.deadline_raw!r})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
