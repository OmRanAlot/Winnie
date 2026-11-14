"""Supabase reads and writes for seats, people, meetings, tasks and task dependencies.

Called by app/services/tasks.py and scripts/seed_example.py. Tables are defined in
supabase/migrations/0001_init.sql. Uses the supabase-py query builder (no ORM). Every function
takes an optional `client` so tests can pass tests/fake_supabase.FakeClient; by default it uses
the singleton from app/integrations/supabase_client.py.

supabase-py has no transactions: insert_extracted_tasks writes all tasks in one batch insert,
but the meeting row is created separately (create_meeting) and stays if that insert fails.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from app.core.deadlines import NEW_YORK, resolve_deadline
from app.domain.models import TASK_STATUSES, ExtractedTask, Task, TaskDependency
from app.integrations.supabase_client import get_client

logger = logging.getLogger(__name__)

UNASSIGNED_SEAT = "Unassigned"
MAX_TASKS = 1000  # list_tasks upper bound; the board has a few hundred tasks a year at most
UNIQUE_VIOLATION = "23505"

Row = dict[str, Any]


class NotFound(LookupError):
    """The referenced meeting or task does not exist."""


class InvalidStatus(ValueError):
    """A status other than 'open', 'done' or 'blocked' was requested (a client error)."""


def _db(client: Client | None) -> Client:
    return client if client is not None else get_client()


def _clean(name: str, what: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError(f"{what} name cannot be empty.")
    return cleaned


def _check_status(status: str) -> None:
    if status not in TASK_STATUSES:
        raise InvalidStatus(f"Invalid task status {status!r}; expected one of {sorted(TASK_STATUSES)}.")


def _aware(moment: datetime) -> datetime:
    return moment.replace(tzinfo=NEW_YORK) if moment.tzinfo is None else moment


# --- seats ------------------------------------------------------------------------------------


def get_or_create_seat(name: str, client: Client | None = None) -> int:
    """Return the id of the seat called `name` (exact match after trimming), creating it if new."""
    db, name = _db(client), _clean(name, "Seat")
    found = db.table("seats").select("id").eq("name", name).limit(1).execute().data
    if found:
        return found[0]["id"]
    try:
        return db.table("seats").insert({"name": name}).execute().data[0]["id"]
    except APIError as error:
        if error.code != UNIQUE_VIOLATION:
            raise
        # Another request created it between our select and insert.
        return db.table("seats").select("id").eq("name", name).limit(1).execute().data[0]["id"]


def _find_seat_id(name: str, db: Client) -> int | None:
    wanted = name.strip().lower()
    seats = db.table("seats").select("id,name").execute().data
    return next((seat["id"] for seat in seats if seat["name"].lower() == wanted), None)


# --- people -----------------------------------------------------------------------------------


def match_person(name: str, people: Sequence[Row]) -> Row | None:
    """Find who `name` refers to among `people` rows ({id, name, aliases}), or None.

    In order: exact name or alias (ignoring case); then a lone first name ("Bob") matching
    exactly one person's first name ("Bob Newman"); then a full name ("Bob Newman") whose first
    word is exactly one person's whole single-word name ("Bob"). Any step that matches more than
    one person returns None (ambiguous), never a guess.
    """
    wanted = " ".join(name.split()).lower()
    if not wanted:
        return None
    exact = [
        person for person in people
        if wanted in (s.lower() for s in [person["name"], *(person.get("aliases") or [])])
    ]  # fmt: skip
    if exact:
        return exact[0] if len(exact) == 1 else None
    words = wanted.split()
    if len(words) == 1:
        candidates = [p for p in people if p["name"].lower().split()[0] == wanted]
    else:
        candidates = [p for p in people if p["name"].lower() == words[0]]
    return candidates[0] if len(candidates) == 1 else None


def get_or_create_person(name: str, client: Client | None = None) -> int:
    """Return the id of the person `name` refers to (see match_person), creating them if new.

    First-name matches are NOT saved as aliases: that would turn a one-time guess into a
    permanent rule (a second "Bob" joining later would still resolve to the first). Aliases are
    curated by hand in the `people.aliases` column.
    """
    db, name = _db(client), _clean(name, "Person")
    people = db.table("people").select("id,name,aliases").execute().data
    match = match_person(name, people)
    if match:
        return match["id"]
    try:
        return db.table("people").insert({"name": name, "aliases": []}).execute().data[0]["id"]
    except APIError as error:
        if error.code != UNIQUE_VIOLATION:
            raise
        # Created by a concurrent request between our select and insert.
        people = db.table("people").select("id,name,aliases").execute().data
        found = match_person(name, people)
        if not found:
            raise
        return found["id"]


# --- meetings and tasks -----------------------------------------------------------------------


def create_meeting(
    held_at: datetime,
    title: str | None,
    transcript: str | None,
    client: Client | None = None,
    recording_id: str | None = None,
) -> int:
    """Insert a meeting and return its id. A naive `held_at` is taken as New York time."""
    row = {
        "held_at": _aware(held_at).isoformat(),
        "title": title,
        "transcript": transcript,
        "recording_id": recording_id,
    }
    return _db(client).table("meetings").insert(row).execute().data[0]["id"]


def find_or_create_meeting(
    held_at: datetime,
    title: str | None,
    transcript: str | None,
    recording_id: str,
    client: Client | None = None,
) -> tuple[int, bool]:
    """Return (meeting id, created) for the meeting of `recording_id`, creating it if new.

    Makes storing a recording's tasks idempotent: a retry finds the existing meeting.
    """
    db = _db(client)

    def existing() -> list[Row]:
        return db.table("meetings").select("id").eq("recording_id", recording_id).limit(1).execute().data

    if found := existing():
        return found[0]["id"], False
    try:
        return create_meeting(held_at, title, transcript, client=db, recording_id=recording_id), True
    except APIError as error:
        if error.code != UNIQUE_VIOLATION or not (found := existing()):
            raise
        return found[0]["id"], False


def save_summary(recording_id: str, summary: str, client: Client | None = None) -> None:
    """Store the AI-written summary on the meeting of `recording_id` (meetings.summary)."""
    _db(client).table("meetings").update({"summary": summary}).eq("recording_id", recording_id).execute()


def tasks_for_meeting(meeting_id: int, client: Client | None = None) -> list[Task]:
    """All tasks extracted from one meeting, in timeline order."""
    db = _db(client)
    rows = db.table("tasks").select("*").eq("source_meeting_id", meeting_id).limit(MAX_TASKS).execute().data
    return sorted(_hydrate(rows, db), key=_timeline_order)


def _task_row(
    task: ExtractedTask, meeting_id: int, held_at: datetime, seat_id: int | None, assignee_id: int | None
) -> Row:
    deadline_at = resolve_deadline(task.deadline, held_at)
    return {
        "title": task.title,
        "description": task.description or None,
        "seat_id": seat_id,
        "assignee_id": assignee_id,
        "rationale": task.rationale or None,
        "deadline_raw": task.deadline,
        "deadline_at": deadline_at.isoformat() if deadline_at else None,
        "needs_review": task.needs_review,
        "source_meeting_id": meeting_id,
        "raw_json": task.model_dump(mode="json"),
    }


def insert_extracted_tasks(
    meeting_id: int, tasks: Iterable[ExtractedTask], client: Client | None = None
) -> list[Task]:
    """Store LLM-extracted tasks for a meeting and return them as Task rows.

    Resolves each seat and assignee to an id (creating them if new; "Unassigned" seats and
    missing assignees stay NULL), parses the spoken deadline against the meeting time
    (unparseable -> deadline_at NULL, the phrase is kept in deadline_raw), and keeps the
    original JSON in raw_json. All tasks go in one batch insert.
    """
    db, tasks = _db(client), list(tasks)
    meetings = db.table("meetings").select("id,held_at").eq("id", meeting_id).limit(1).execute().data
    if not meetings:
        raise NotFound(f"Meeting {meeting_id} does not exist.")
    if not tasks:
        return []
    held_at = datetime.fromisoformat(meetings[0]["held_at"])
    seat_ids: dict[str, int] = {}
    person_ids: dict[str, int] = {}
    rows = []
    for task in tasks:
        seat_id = None
        if task.seat and task.seat != UNASSIGNED_SEAT:
            if task.seat not in seat_ids:
                seat_ids[task.seat] = get_or_create_seat(task.seat, client=db)
            seat_id = seat_ids[task.seat]
        assignee_id = None
        if task.assignee:
            if task.assignee not in person_ids:
                person_ids[task.assignee] = get_or_create_person(task.assignee, client=db)
            assignee_id = person_ids[task.assignee]
        rows.append(_task_row(task, meeting_id, held_at, seat_id, assignee_id))
    inserted = db.table("tasks").insert(rows).execute().data
    unparsed = sum(1 for row in rows if row["deadline_raw"] and not row["deadline_at"])
    logger.info(
        "Stored %d tasks for meeting %s (%d deadlines left unparsed)", len(inserted), meeting_id, unparsed
    )
    return _hydrate(inserted, db)


def _values_by_id(db: Client, table: str, ids: set[int], column: str) -> dict[int, Any]:
    if not ids:
        return {}
    rows = db.table(table).select(f"id,{column}").in_("id", sorted(ids)).execute().data
    return {row["id"]: row[column] for row in rows}


def _hydrate(rows: Sequence[Row], db: Client) -> list[Task]:
    """Attach seat/assignee names, the meeting time and dependency ids to raw task rows."""
    if not rows:
        return []
    seats = _values_by_id(db, "seats", {r["seat_id"] for r in rows if r.get("seat_id")}, "name")
    people = _values_by_id(db, "people", {r["assignee_id"] for r in rows if r.get("assignee_id")}, "name")
    meeting_ids = {r["source_meeting_id"] for r in rows if r.get("source_meeting_id")}
    meetings = _values_by_id(db, "meetings", meeting_ids, "held_at")
    edges = (
        db.table("task_dependencies").select("task_id,depends_on_id")
        .in_("task_id", [r["id"] for r in rows]).execute().data
    )  # fmt: skip
    depends_on: dict[int, list[int]] = {}
    for edge in edges:
        depends_on.setdefault(edge["task_id"], []).append(edge["depends_on_id"])
    return [
        Task(
            **row,
            seat=seats.get(row.get("seat_id")),
            assignee=people.get(row.get("assignee_id")),
            meeting_held_at=meetings.get(row.get("source_meeting_id")),
            depends_on=tuple(sorted(depends_on.get(row["id"], []))),
        )
        for row in rows
    ]


def _timeline_order(task: Task) -> tuple[bool, float, float, int]:
    """Scheduled tasks first, by deadline; then unscheduled; ties by creation time and id."""
    deadline = task.deadline_at.timestamp() if task.deadline_at else 0.0
    return (task.deadline_at is None, deadline, task.created_at.timestamp(), task.id)


def list_tasks(
    status: str | None = None,
    assignee: str | None = None,
    seat: str | None = None,
    client: Client | None = None,
) -> list[Task]:
    """Tasks ordered by deadline (unscheduled last), optionally filtered.

    `assignee` is resolved like get_or_create_person (so "Bob" finds "Bob Newman"); `seat` is
    matched ignoring case. An unknown assignee or seat returns an empty list.
    """
    db = _db(client)
    query = db.table("tasks").select("*")
    if status is not None:
        _check_status(status)
        query = query.eq("status", status)
    if assignee is not None:
        person = match_person(assignee, db.table("people").select("id,name,aliases").execute().data)
        if not person:
            return []
        query = query.eq("assignee_id", person["id"])
    if seat is not None:
        seat_id = _find_seat_id(seat, db)
        if seat_id is None:
            return []
        query = query.eq("seat_id", seat_id)
    rows = query.order("deadline_at", nullsfirst=False).limit(MAX_TASKS).execute().data
    return sorted(_hydrate(rows, db), key=_timeline_order)


def update_task_status(task_id: int, status: str, client: Client | None = None) -> Task:
    """Set a task's status ('open', 'done' or 'blocked'); updated_at is set by the DB trigger."""
    _check_status(status)
    db = _db(client)
    rows = db.table("tasks").update({"status": status}).eq("id", task_id).execute().data
    if not rows:
        raise NotFound(f"Task {task_id} does not exist.")
    logger.info("Task %s status -> %s", task_id, status)
    return _hydrate(rows, db)[0]


# --- dependencies -----------------------------------------------------------------------------


def would_create_cycle(edges: Iterable[tuple[int, int]], task_id: int, depends_on_id: int) -> bool:
    """True if adding "task_id waits on depends_on_id" would close a loop in `edges`."""
    waits_on: dict[int, set[int]] = {}
    for waiting, needed in edges:
        waits_on.setdefault(waiting, set()).add(needed)
    stack, seen = [depends_on_id], set()
    while stack:
        current = stack.pop()
        if current == task_id:
            return True
        if current not in seen:
            seen.add(current)
            stack.extend(waits_on.get(current, ()))
    return False


def add_dependency(task_id: int, depends_on_id: int, client: Client | None = None) -> TaskDependency:
    """Record that `task_id` waits on `depends_on_id`. Idempotent; rejects self-links and cycles."""
    edge = TaskDependency(task_id=task_id, depends_on_id=depends_on_id)  # rejects self-links
    db = _db(client)
    found = db.table("tasks").select("id").in_("id", [task_id, depends_on_id]).execute().data
    if len(found) < 2:
        raise NotFound(f"Task {task_id} or {depends_on_id} does not exist.")
    rows = db.table("task_dependencies").select("task_id,depends_on_id").execute().data
    edges = [(row["task_id"], row["depends_on_id"]) for row in rows]
    if (task_id, depends_on_id) in edges:
        return edge
    if would_create_cycle(edges, task_id, depends_on_id):
        raise ValueError(f"Task {task_id} waiting on {depends_on_id} would create a dependency cycle.")
    try:
        db.table("task_dependencies").insert(edge.model_dump()).execute()
    except APIError as error:
        if error.code != UNIQUE_VIOLATION:
            raise
    logger.info("Task %s now waits on task %s", task_id, depends_on_id)
    return edge
