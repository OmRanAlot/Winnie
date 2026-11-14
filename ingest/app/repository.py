"""All database access (psycopg3). Every write is parameterized; tasks/tasks_placeholder are only
ever touched by INSERT, single-row UPDATE (by id) and SELECT. No DDL, no bulk updates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.config import OwnerCodeKind
from app.deadlines import NEW_YORK, resolve_deadline
from app.models import ExtractedTask, MeetingStatus, Member, MemberKind, Segment

Row = dict[str, Any]

MEETING_COLS = (
    "id, title, held_at, duration_seconds, audio_bucket, audio_path, audio_mime, audio_bytes, "
    "audio_sha256, status, error, transcript_text, summary, transcription_model, summary_model, "
    "created_at, updated_at"
)
TASK_UPDATABLE = (
    "title", "description", "status", "owner_code", "due_date", "event_tag", "tags",
    "stakeholder_codes",
)  # fmt: skip
TASK_STATUSES = ("todo", "in_progress", "blocked", "done")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,49}$")
TITLE_MAX = 200
MAX_CODE_ATTEMPTS = 5


# ---------------------------------------------------------------- pure helpers


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def month_code_for(held_at: datetime) -> str:
    """YYYY-MM in the club's timezone (the tasks.month_code convention)."""
    return held_at.astimezone(NEW_YORK).strftime("%Y-%m")


def format_task_code(month_code: str, n: int) -> str:
    """WIN-YYYYMM-<n>. The live DB trigger overwrites this on insert with the same shape."""
    return f"WIN-{month_code.replace('-', '')}-{n}"


def match_member(
    members: Sequence[Member], text: str | None, kind: MemberKind | None = None
) -> tuple[Member | None, bool]:
    """Resolve free text to a member. Returns (member, ambiguous).

    1. exact (case-insensitive) match on code, name or alias; 2. otherwise every query word must
    be a whole word of the member's name ("Bob" -> "Bob Newman"). Exactly one hit resolves;
    several hits are ambiguous (None, True); none is (None, False)."""
    query = _norm(text or "")
    if not query:
        return None, False
    pool = [m for m in members if m.active and (kind is None or m.kind == kind)]
    exact = [
        m for m in pool
        if query in {_norm(m.code), _norm(m.name), *(_norm(a) for a in m.aliases)}
    ]  # fmt: skip
    if len(exact) == 1:
        return exact[0], False
    if len(exact) > 1:
        return None, True
    words = set(query.split())
    partial = [m for m in pool if words <= set(_norm(m.name).split())]
    if len(partial) == 1:
        return partial[0], False
    return None, len(partial) > 1


def _to_member(row: Row) -> Member:
    return Member(
        id=row["id"], code=row["code"], kind=row["kind"], name=row["name"], seat=row["seat"],
        aliases=tuple(row["aliases"] or ()), active=row["active"],
    )  # fmt: skip


def _owner_code(
    kind: OwnerCodeKind, seat: Member | None, person: Member | None, members: Sequence[Member]
) -> str | None:
    """Which code goes into tasks.owner_code, per what the codes refer to."""
    seat_code = seat.code if seat else None
    if seat_code is None and person is not None and person.seat:
        held, _ = match_member(members, person.seat, "seat")
        seat_code = held.code if held else None
    person_code = person.code if person else None
    if kind == "seat":
        return seat_code
    if kind == "person":
        return person_code
    return person_code or seat_code


# ---------------------------------------------------------------- repository


class Repository:
    def __init__(self, pool: Any, owner_code_kind: OwnerCodeKind = "seat") -> None:
        self.pool: ConnectionPool[Any] = pool
        self.owner_code_kind = owner_code_kind

    # ---- members
    def add_member(
        self,
        code: str,
        name: str,
        kind: MemberKind = "person",
        seat: str | None = None,
        aliases: Sequence[str] = (),
    ) -> Member:
        if not CODE_RE.match(code):
            raise ValueError(f"member code {code!r} must match {CODE_RE.pattern}")
        with self.pool.connection() as conn:
            row = conn.execute(
                "insert into public.members (code, kind, name, seat, aliases) "
                "values (%s, %s, %s, %s, %s) returning *",
                (code, kind, name, seat, list(aliases)),
            ).fetchone()
        assert row is not None
        return _to_member(row)

    def list_members(self, kind: MemberKind | None = None, active_only: bool = True) -> list[Member]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "select * from public.members where (%s::text is null or kind = %s) "
                "and (not %s or active) order by kind, code",
                (kind, kind, active_only),
            ).fetchall()
        return [_to_member(r) for r in rows]

    def get_or_create_member(
        self,
        text: str,
        kind: MemberKind = "person",
        *,
        create_missing: bool = False,
        code: str | None = None,
    ) -> Member | None:
        """Resolve `text` to a member of `kind`. Ambiguous -> None. No match -> None unless
        create_missing, which creates a member (code given, or derived from the text)."""
        found, ambiguous = match_member(self.list_members(kind), text, kind)
        if found or ambiguous or not create_missing:
            return found
        derived = code or re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")
        if not CODE_RE.match(derived):
            derived = f"M_{derived}"[:50]
        return self.add_member(derived, text.strip(), kind, aliases=[_norm(text)])

    # ---- meetings
    def create_meeting(
        self,
        *,
        title: str | None,
        held_at: datetime,
        audio_path: str | None,
        audio_mime: str | None,
        audio_bytes: int | None,
        audio_sha256: str,
        audio_bucket: str = "meeting-audio",
        duration_seconds: int | None = None,
    ) -> tuple[Row, bool]:
        """Insert, or return the existing meeting with the same audio hash. -> (row, created)."""
        with self.pool.connection() as conn:
            row = conn.execute(
                "insert into public.meetings (title, held_at, audio_bucket, audio_path, audio_mime,"
                " audio_bytes, audio_sha256, duration_seconds) values (%s,%s,%s,%s,%s,%s,%s,%s) "
                f"on conflict (audio_sha256) do nothing returning {MEETING_COLS}",
                (title, held_at, audio_bucket, audio_path, audio_mime, audio_bytes, audio_sha256,
                 duration_seconds),
            ).fetchone()  # fmt: skip
            if row is not None:
                return row, True
            existing = conn.execute(
                f"select {MEETING_COLS} from public.meetings where audio_sha256 = %s",
                (audio_sha256,),
            ).fetchone()
        assert existing is not None
        return existing, False

    def set_meeting_status(
        self, meeting_id: int, status: MeetingStatus, error: str | None = None
    ) -> None:
        with self.pool.connection() as conn:
            cur = conn.execute(
                "update public.meetings set status = %s, error = %s where id = %s",
                (status, error if status == "failed" else None, meeting_id),
            )
            if cur.rowcount != 1:
                raise LookupError(f"meeting {meeting_id} not found")

    def add_attendees(self, meeting_id: int, member_ids: Sequence[int]) -> None:
        with self.pool.connection() as conn:
            for member_id in dict.fromkeys(member_ids):
                conn.execute(
                    "insert into public.meeting_attendees (meeting_id, member_id) values (%s, %s) "
                    "on conflict do nothing",
                    (meeting_id, member_id),
                )

    def save_transcript(self, meeting_id: int, segments: Sequence[Segment], model: str) -> None:
        """Replace segments and the full text in ONE transaction (safe to re-run on resume)."""
        text = "\n".join(s.text for s in segments)
        with self.pool.connection() as conn, conn.transaction():
            upd = conn.execute(
                "update public.meetings set transcript_text = %s, transcription_model = %s "
                "where id = %s",
                (text, model, meeting_id),
            )
            if upd.rowcount != 1:
                raise LookupError(f"meeting {meeting_id} not found")
            conn.execute(
                "delete from public.transcript_segments where meeting_id = %s", (meeting_id,)
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into public.transcript_segments "
                    "(meeting_id, idx, start_ms, end_ms, speaker_label, text) "
                    "values (%s,%s,%s,%s,%s,%s)",
                    [(meeting_id, s.idx, s.start_ms, s.end_ms, s.speaker_label, s.text)
                     for s in segments],
                )  # fmt: skip

    def save_summary(self, meeting_id: int, summary: str, model: str) -> None:
        with self.pool.connection() as conn:
            cur = conn.execute(
                "update public.meetings set summary = %s, summary_model = %s where id = %s",
                (summary, model, meeting_id),
            )
            if cur.rowcount != 1:
                raise LookupError(f"meeting {meeting_id} not found")

    def get_meeting(self, meeting_id: int) -> Row | None:
        with self.pool.connection() as conn:
            meeting = conn.execute(
                f"select {MEETING_COLS} from public.meetings where id = %s", (meeting_id,)
            ).fetchone()
            if meeting is None:
                return None
            meeting["attendees"] = conn.execute(
                "select m.* from public.meeting_attendees a join public.members m "
                "on m.id = a.member_id where a.meeting_id = %s order by m.code",
                (meeting_id,),
            ).fetchall()
            meeting["segments"] = conn.execute(
                "select idx, start_ms, end_ms, speaker_label, member_id, text "
                "from public.transcript_segments where meeting_id = %s order by idx",
                (meeting_id,),
            ).fetchall()
            meeting["tasks"] = conn.execute(
                "select t.*, l.rationale, l.needs_review, l.deadline_raw from public.tasks t "
                "join public.task_meeting_links l on l.task_id = t.id "
                "where l.meeting_id = %s order by t.created_at, t.task_code",
                (meeting_id,),
            ).fetchall()
        return meeting

    def get_meeting_by_sha(self, sha256: str) -> Row | None:
        with self.pool.connection() as conn:
            return conn.execute(
                f"select {MEETING_COLS} from public.meetings where audio_sha256 = %s", (sha256,)
            ).fetchone()

    def list_meetings(self, limit: int = 50) -> list[Row]:
        with self.pool.connection() as conn:
            return conn.execute(
                "select id, title, held_at, status, error, (summary is not null) as has_summary "
                "from public.meetings order by held_at desc limit %s",
                (limit,),
            ).fetchall()

    def search_transcripts(self, query: str, limit: int = 20) -> list[Row]:
        with self.pool.connection() as conn:
            return conn.execute(
                "select m.id, m.title, m.held_at, ts_rank(m.transcript_tsv, q) as rank, "
                "ts_headline('english', m.transcript_text, q, 'MaxFragments=2,MaxWords=25') "
                "as snippet from public.meetings m, websearch_to_tsquery('english', %s) q "
                "where m.transcript_tsv @@ q order by rank desc, m.held_at desc limit %s",
                (query, limit),
            ).fetchall()

    # ---- tasks
    def _insert_task(self, conn: psycopg.Connection[Any], f: Mapping[str, Any]) -> Row:
        """Insert one task, generating a unique task_code (retrying on collision)."""
        for _ in range(MAX_CODE_ATTEMPTS):
            nxt = conn.execute(
                "select coalesce(max(substring(task_code from '[0-9]+$')::bigint), 0) + 1 as n "
                "from public.tasks where task_code ~ %s",
                (f"^WIN-{f['month_code'].replace('-', '')}-[0-9]+$",),
            ).fetchone()
            assert nxt is not None
            try:
                with conn.transaction():  # savepoint, so a collision doesn't poison the outer tx
                    row = conn.execute(
                        "insert into public.tasks (task_code, title, description, month_code, "
                        "status, stakeholder_codes, owner_code, due_date, event_tag, tags, source, "
                        "source_reference) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "returning *",
                        (format_task_code(f["month_code"], nxt["n"]), f["title"][:TITLE_MAX],
                         f.get("description", ""), f["month_code"], f.get("status", "todo"),
                         list(f.get("stakeholder_codes", ())), f.get("owner_code"),
                         f.get("due_date"), f.get("event_tag"), list(f.get("tags", ())),
                         f.get("source", "manual"), f.get("source_reference")),
                    ).fetchone()  # fmt: skip
            except pg_errors.UniqueViolation:
                continue
            assert row is not None
            return row
        raise RuntimeError("could not generate a unique task_code")

    def add_task(self, **fields: Any) -> Row:
        """Create one task. Required: title, month_code. See _insert_task for optional fields."""
        with self.pool.connection() as conn:
            return self._insert_task(conn, fields)

    def insert_extracted_tasks(self, meeting_id: int, items: Sequence[ExtractedTask]) -> list[Row]:
        """Map extracted items to tasks + task_meeting_links, atomically. Re-running for a meeting
        that already has links returns the existing tasks instead of duplicating."""
        members = self.list_members(active_only=True)
        with self.pool.connection() as conn, conn.transaction():
            meeting = conn.execute(
                "select held_at from public.meetings where id = %s", (meeting_id,)
            ).fetchone()
            if meeting is None:
                raise LookupError(f"meeting {meeting_id} not found")
            existing = conn.execute(
                "select t.* from public.tasks t join public.task_meeting_links l "
                "on l.task_id = t.id where l.meeting_id = %s order by t.created_at",
                (meeting_id,),
            ).fetchall()
            if existing:
                return existing
            held_at: datetime = meeting["held_at"]
            created: list[Row] = []
            for item in items:
                seat, seat_amb = match_member(members, item.seat, "seat")
                person, person_amb = match_member(members, item.assignee, "person")
                owner = _owner_code(self.owner_code_kind, seat, person, members)
                deadline = resolve_deadline(item.deadline, held_at)
                needs_review = (
                    item.needs_review
                    or owner is None
                    or seat_amb
                    or person_amb
                    or bool(item.seat and seat is None)
                    or bool(item.assignee and person is None)
                    or bool(item.deadline and deadline is None)
                )
                task = self._insert_task(conn, {
                    "title": item.title.strip() or "Untitled action item",
                    "description": item.description,
                    "month_code": month_code_for(held_at),
                    "status": "todo",
                    "owner_code": owner,
                    "due_date": deadline.date() if deadline else None,
                    "source": "meeting",
                    "source_reference": f"meeting:{meeting_id}",
                })  # fmt: skip
                conn.execute(
                    "insert into public.task_meeting_links (task_id, meeting_id, rationale, "
                    "needs_review, deadline_raw, raw_json) values (%s,%s,%s,%s,%s,%s)",
                    (task["id"], meeting_id, item.rationale, needs_review, item.deadline,
                     Jsonb(item.model_dump())),
                )  # fmt: skip
                created.append(task)
            return created

    def list_tasks(
        self,
        *,
        status: str | None = None,
        owner_code: str | None = None,
        month_code: str | None = None,
        source: str | None = None,
        meeting_id: int | None = None,
        due_before: date | None = None,
        limit: int = 100,
    ) -> list[Row]:
        where: list[str] = []
        params: list[Any] = []
        for clause, value in (
            ("t.status = %s", status),
            ("t.owner_code = %s", owner_code),
            ("t.month_code = %s", month_code),
            ("t.source = %s", source),
            ("t.due_date <= %s", due_before),
        ):
            if value is not None:
                where.append(clause)
                params.append(value)
        if meeting_id is not None:
            where.append(
                "exists (select 1 from public.task_meeting_links l "
                "where l.task_id = t.id and l.meeting_id = %s)"
            )
            params.append(meeting_id)
        sql = "select t.* from public.tasks t"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by t.created_at desc, t.task_code limit %s"
        with self.pool.connection() as conn:
            return conn.execute(sql, [*params, limit]).fetchall()

    def update_task(self, ref: str | UUID, **fields: Any) -> Row:
        """Update ONE task, identified by uuid or task_code. Only whitelisted columns."""
        unknown = set(fields) - set(TASK_UPDATABLE)
        if unknown:
            raise ValueError(f"cannot update: {sorted(unknown)}")
        if not fields:
            raise ValueError("nothing to update")
        if "status" in fields and fields["status"] not in TASK_STATUSES:
            raise ValueError(f"status must be one of {TASK_STATUSES}")
        assignments = ", ".join(f"{col} = %s" for col in fields)  # col names are whitelisted
        try:
            key, where = str(UUID(str(ref))), "id = %s::uuid"
        except ValueError:
            key, where = str(ref), "task_code = %s"
        with self.pool.connection() as conn:
            row = conn.execute(
                f"update public.tasks set {assignments} where {where} returning *",
                [*fields.values(), key],
            ).fetchone()
        if row is None:
            raise LookupError(f"task {ref} not found")
        return row

    def add_dependency(self, task_id: UUID | str, depends_on_id: UUID | str) -> None:
        """task_id waits on depends_on_id. Rejects self-dependency and cycles."""
        a, b = str(task_id), str(depends_on_id)
        if a == b:
            raise ValueError("a task cannot depend on itself")
        with self.pool.connection() as conn:
            cycle = conn.execute(
                "with recursive chain(id) as (select %s::uuid union select d.depends_on_id "
                "from public.task_dependencies d join chain c on d.task_id = c.id) "
                "select 1 from chain where id = %s::uuid",
                (b, a),
            ).fetchone()
            if cycle:
                raise ValueError("dependency would create a cycle")
            conn.execute(
                "insert into public.task_dependencies (task_id, depends_on_id) "
                "values (%s::uuid, %s::uuid) on conflict do nothing",
                (a, b),
            )
