"""Meeting persistence and timeline projection over the canonical UUID task store.

Tracker imports, messaging, and meeting extraction share public.tasks. Timeline
names are display text, never verified membership. The legacy seat/person helpers
remain for compatibility tooling; ingestion does not call them.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

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
    """An unsupported task status was requested (a client error)."""


def _db(client: Client | None) -> Client:
    return client if client is not None else get_client()


def _clean(name: str, what: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError(f"{what} name cannot be empty.")
    return cleaned


def _check_status(status: str) -> None:
    if status not in TASK_STATUSES and status != "open":
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


def _task_row(task: ExtractedTask, meeting_id: int, held_at: datetime, index: int) -> Row:
    deadline = resolve_deadline(task.deadline, held_at)
    local = held_at.astimezone(NEW_YORK)
    return {
        # Stable per meeting slot: concurrent retries cannot insert a second task set.
        "id": str(uuid5(NAMESPACE_URL, f"winnie:meeting:{meeting_id}:task:{index}")),
        "title": task.title,
        "description": task.description,
        "month_code": local.strftime("%Y-%m"),
        "semester_code": f"{'spring' if local.month <= 5 else 'summer' if local.month <= 8 else 'fall'}-{local.year}",
        "source": "meeting",
        "source_reference": f"meeting:{meeting_id}",
        "seat_text": task.seat if task.seat != UNASSIGNED_SEAT else None,
        "assignee_text": task.assignee or "",
        "rationale": task.rationale or None,
        "deadline_text": task.deadline or "",
        "due_date": deadline.astimezone(NEW_YORK).date().isoformat() if deadline else None,
        "deadline_at": deadline.isoformat() if deadline else None,
        "needs_review": task.needs_review,
        "source_meeting_id": meeting_id,
        "raw_json": task.model_dump(mode="json"),
    }


def insert_extracted_tasks(
    meeting_id: int, tasks: Iterable[ExtractedTask], client: Client | None = None
) -> list[Task]:
    """Insert meeting actions into the same UUID task table used by tracker/messaging.

    Extracted names remain text; they never create or impersonate verified members.
    """
    db, tasks = _db(client), list(tasks)
    meetings = db.table("meetings").select("id,held_at").eq("id", meeting_id).limit(1).execute().data
    if not meetings:
        raise NotFound(f"Meeting {meeting_id} does not exist.")
    if not tasks:
        return []
    held_at = datetime.fromisoformat(meetings[0]["held_at"])
    rows = [_task_row(task, meeting_id, held_at, index) for index, task in enumerate(tasks)]
    try:
        inserted = db.table("tasks").insert(rows).execute().data
    except APIError as error:
        if error.code != UNIQUE_VIOLATION:
            raise
        existing = tasks_for_meeting(meeting_id, client=db)
        if not existing:
            raise
        return existing
    return _hydrate(inserted, db)


def _values_by_id(db: Client, table: str, ids: set[int], column: str) -> dict[int, Any]:
    if not ids:
        return {}
    rows = db.table(table).select(f"id,{column}").in_("id", sorted(ids)).execute().data
    return {row["id"]: row[column] for row in rows}


def _hydrate(rows: Sequence[Row], db: Client) -> list[Task]:
    """Project canonical task records into timeline fields, preserving UUID dependency links."""
    if not rows:
        return []
    meetings = _values_by_id(
        db, "meetings", {r["source_meeting_id"] for r in rows if r.get("source_meeting_id")}, "held_at"
    )
    edges = db.table("task_dependencies").select("task_id,depends_on_id").in_(
        "task_id", [r["id"] for r in rows]
    ).execute().data
    depends_on: dict[str, list[str]] = {}
    for edge in edges:
        depends_on.setdefault(edge["task_id"], []).append(edge["depends_on_id"])
    result = []
    for row in rows:
        due = row.get("due_date")
        precise = datetime.fromisoformat(row["deadline_at"]) if row.get("deadline_at") else None
        # due_date is canonical. A tracker edit/clear must not resurrect an old timestamp.
        if due:
            date_value = datetime.fromisoformat(str(due)).date()
            if precise is None or precise.astimezone(NEW_YORK).date() != date_value:
                precise = datetime.combine(date_value, time.min, tzinfo=NEW_YORK)
        else:
            precise = None
        assignee = row.get("assignee_text") or row.get("owner_code") or None
        result.append(Task(
            id=row["id"], title=row["title"], description=row.get("description"),
            status=row["status"], seat=row.get("seat_text"), assignee=assignee,
            assignee_id=row.get("owner_code") or (f"name:{assignee.casefold()}" if assignee else None),
            deadline_raw=row.get("deadline_text"), deadline_at=precise,
            rationale=row.get("rationale"), needs_review=row.get("needs_review", False),
            source_meeting_id=row.get("source_meeting_id"), raw_json=row.get("raw_json"),
            created_at=row["created_at"], updated_at=row["updated_at"],
            meeting_held_at=meetings.get(row.get("source_meeting_id")),
            depends_on=tuple(sorted(depends_on.get(row["id"], []))),
        ))
    return result


def _timeline_order(task: Task) -> tuple[bool, float, float, str]:
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
        query = query.eq("status", "todo" if status == "open" else status)
    rows = query.order("due_date", nullsfirst=False).limit(MAX_TASKS).execute().data
    tasks = sorted(_hydrate(rows, db), key=_timeline_order)
    if assignee is not None:
        people = [{"id": name, "name": name, "aliases": []}
                  for name in sorted({t.assignee for t in tasks if t.assignee})]
        person = match_person(assignee, people)
        tasks = [t for t in tasks if person and t.assignee == person["name"]]
    if seat is not None:
        tasks = [t for t in tasks if t.seat and t.seat.casefold() == seat.strip().casefold()]
    return tasks


def update_task_status(task_id: str, status: str, client: Client | None = None) -> Task:
    """Set canonical status; the legacy input "open" is translated to "todo"."""
    _check_status(status)
    status = "todo" if status == "open" else status
    db = _db(client)
    rows = db.table("tasks").update({"status": status}).eq("id", task_id).execute().data
    if not rows:
        raise NotFound(f"Task {task_id} does not exist.")
    logger.info("Task %s status -> %s", task_id, status)
    return _hydrate(rows, db)[0]


# --- dependencies -----------------------------------------------------------------------------


def would_create_cycle(edges: Iterable[tuple[str, str]], task_id: str, depends_on_id: str) -> bool:
    """True if adding "task_id waits on depends_on_id" would close a loop in `edges`."""
    waits_on: dict[str, set[str]] = {}
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


def add_dependency(task_id: str, depends_on_id: str, client: Client | None = None) -> TaskDependency:
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


def add_dependencies(
    pairs: Iterable[tuple[str, str]], client: Client | None = None
) -> list[TaskDependency]:
    """Atomically validate and persist a batch of new dependency edges."""
    requested = [TaskDependency(task_id=task_id, depends_on_id=depends_on_id)
                 for task_id, depends_on_id in pairs]
    if not requested:
        return []

    db = _db(client)
    task_ids = sorted({edge.task_id for edge in requested} | {edge.depends_on_id for edge in requested})
    found = db.table("tasks").select("id").in_("id", task_ids).execute().data
    if len(found) != len(task_ids):
        found_ids = {row["id"] for row in found}
        missing = next(task_id for task_id in task_ids if task_id not in found_ids)
        raise NotFound(f"Task {missing} does not exist.")

    rows = db.table("task_dependencies").select("task_id,depends_on_id").execute().data
    graph = {(row["task_id"], row["depends_on_id"]) for row in rows}
    added = []
    for edge in requested:
        pair = (edge.task_id, edge.depends_on_id)
        if pair in graph:
            continue
        if would_create_cycle(graph, edge.task_id, edge.depends_on_id):
            raise ValueError(
                f"Task {edge.task_id} waiting on {edge.depends_on_id} would create a dependency cycle."
            )
        graph.add(pair)
        added.append(edge)

    if added:
        db.table("task_dependencies").insert([edge.model_dump() for edge in added]).execute()
        logger.info("Added %s task dependency links", len(added))
    return added
