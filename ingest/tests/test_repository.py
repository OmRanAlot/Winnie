"""Repository integration tests against the local throwaway Postgres (fresh DB per test)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pytest

from app.db import make_pool
from app.deadlines import NEW_YORK
from app.models import ExtractedTask, Segment
from app.repository import Repository

HELD = datetime(2026, 11, 13, 18, 0, tzinfo=NEW_YORK)  # a Friday evening


def new_meeting(repo: Repository, sha: str = "sha1") -> int:
    row, created = repo.create_meeting(title="Board", held_at=HELD, audio_path=f"{sha}.wav",
                                       audio_mime="audio/wav", audio_bytes=3, audio_sha256=sha)  # fmt: skip
    assert created
    return int(row["id"])


@pytest.fixture
def seeded(repo: Repository) -> Repository:
    repo.add_member("TREAS", "Treasurer", "seat", aliases=["treasurer"])
    repo.add_member("SEC", "Secretary", "seat")
    repo.add_member("BOBN", "Bob Newman", "person", seat="Secretary")
    repo.add_member("ALI", "Alice Park", "person")
    return repo


def count(repo: Repository, table: str) -> int:
    with repo.pool.connection() as c:
        row = c.execute(f"select count(*) n from public.{table}").fetchone()  # type: ignore[arg-type]
    assert row
    return int(row["n"])


# ---- members
def test_add_member_validates_code(repo: Repository):
    with pytest.raises(ValueError):
        repo.add_member("lower-case", "x")
    m = repo.add_member("VP", "Vice President", "seat", aliases=["vp"])
    assert (m.code, m.kind, m.aliases) == ("VP", "seat", ("vp",))


def test_get_or_create_member(seeded: Repository):
    bob = seeded.get_or_create_member("bob", "person")
    assert bob is not None and bob.code == "BOBN"
    assert seeded.get_or_create_member("Zed", "person") is None
    seeded.add_member("BOBS", "Bob Smith")
    assert seeded.get_or_create_member("Bob", "person") is None  # now ambiguous
    created = seeded.get_or_create_member("Zed Zimmer", "person", create_missing=True)
    assert created is not None and created.code == "ZED_ZIMMER"
    again = seeded.get_or_create_member("zed zimmer", "person")
    assert again is not None and again.id == created.id


def test_get_or_create_does_not_create_when_ambiguous(seeded: Repository):
    seeded.add_member("BOBS", "Bob Smith")
    assert seeded.get_or_create_member("Bob", "person", create_missing=True) is None
    assert len(seeded.list_members("person")) == 3


# ---- meetings
def test_create_meeting_is_idempotent_on_sha(repo: Repository):
    first, created1 = repo.create_meeting(title="A", held_at=HELD, audio_path="p", audio_mime="m",
                                          audio_bytes=1, audio_sha256="same")  # fmt: skip
    second, created2 = repo.create_meeting(title="B", held_at=HELD, audio_path="p", audio_mime="m",
                                           audio_bytes=1, audio_sha256="same")  # fmt: skip
    assert created1 and not created2 and first["id"] == second["id"] and second["title"] == "A"
    assert count(repo, "meetings") == 1


def test_set_meeting_status_and_error(repo: Repository):
    mid = new_meeting(repo)
    repo.set_meeting_status(mid, "failed", "boom")
    meeting = repo.get_meeting(mid)
    assert meeting and (meeting["status"], meeting["error"]) == ("failed", "boom")
    repo.set_meeting_status(mid, "transcribing", "ignored")
    meeting = repo.get_meeting(mid)
    assert meeting and meeting["error"] is None
    with pytest.raises(LookupError):
        repo.set_meeting_status(9999, "done")


def test_save_transcript_replaces_segments_and_text_atomically(repo: Repository):
    mid = new_meeting(repo)
    segs = [Segment(0, 0, 1000, "A", "Hello team."), Segment(1, 1000, 2000, None, "Order pizza.")]
    repo.save_transcript(mid, segs, "whisper-x")
    repo.save_transcript(mid, segs[:1], "whisper-x")  # re-run: replaced, not duplicated
    meeting = repo.get_meeting(mid)
    assert meeting and meeting["transcript_text"] == "Hello team."
    assert [s["text"] for s in meeting["segments"]] == ["Hello team."]
    assert meeting["transcription_model"] == "whisper-x"
    with pytest.raises(LookupError):  # unknown meeting: the whole transaction rolls back
        repo.save_transcript(9999, segs, "m")


def test_save_summary_and_search(repo: Repository):
    mid = new_meeting(repo)
    repo.save_transcript(mid, [Segment(0, 0, 1, None, "The treasurer will order pizza")], "m")
    repo.save_summary(mid, "Pizza ordered", "claude-x")
    other = new_meeting(repo, "sha2")
    repo.save_transcript(other, [Segment(0, 0, 1, None, "Sponsor outreach plans")], "m")
    hits = repo.search_transcripts("pizza")
    assert [h["id"] for h in hits] == [mid]
    assert "pizza" in hits[0]["snippet"].lower()
    assert repo.search_transcripts("zzzz") == []
    meeting = repo.get_meeting(mid)
    assert meeting and meeting["summary"] == "Pizza ordered" and meeting["summary_model"] == "claude-x"
    assert repo.get_meeting(424242) is None


def test_attendees(seeded: Repository):
    mid = new_meeting(seeded)
    ids = [m.id for m in seeded.list_members("person")]
    seeded.add_attendees(mid, ids + ids)  # duplicates ignored
    meeting = seeded.get_meeting(mid)
    assert meeting and len(meeting["attendees"]) == 2


# ---- extracted tasks
def item(**kw: Any) -> ExtractedTask:
    return ExtractedTask(**{"title": "Do thing", **kw})


def test_insert_extracted_tasks_maps_every_field(seeded: Repository):
    mid = new_meeting(seeded)
    before = count(seeded, "tasks")
    rows = seeded.insert_extracted_tasks(mid, [
        item(title="Order pizza", description="for kickoff", seat="Treasurer",
             deadline="by Monday noon", rationale="said so"),
        item(title="Send email", assignee="Bob", deadline="tonight"),
    ])  # fmt: skip
    assert count(seeded, "tasks") == before + 2
    pizza, email = rows
    assert pizza["owner_code"] == "TREAS"
    assert pizza["due_date"] == date(2026, 11, 16)  # Monday after the Friday meeting
    assert (pizza["status"], pizza["source"], pizza["month_code"]) == ("todo", "meeting", "2026-11")
    assert pizza["source_reference"] == f"meeting:{mid}"
    assert pizza["tags"] == [] and pizza["stakeholder_codes"] == []
    assert pizza["description"] == "for kickoff"
    # seats mode: Bob resolves to a person who holds Secretary -> owner is the SEC seat code
    assert email["owner_code"] == "SEC" and email["due_date"] == date(2026, 11, 13)
    assert re.fullmatch(r"WIN-202611-\d+", pizza["task_code"])
    assert pizza["task_code"] != email["task_code"]
    meeting = seeded.get_meeting(mid)
    assert meeting and [t["title"] for t in meeting["tasks"]] == ["Order pizza", "Send email"]
    assert meeting["tasks"][0]["rationale"] == "said so"
    assert meeting["tasks"][0]["needs_review"] is False
    assert meeting["tasks"][0]["deadline_raw"] == "by Monday noon"
    with seeded.pool.connection() as c:
        raw = c.execute("select raw_json from public.task_meeting_links limit 1").fetchone()
    assert raw and raw["raw_json"]["title"] in {"Order pizza", "Send email"}


def test_unresolved_owner_or_deadline_flags_needs_review(seeded: Repository):
    mid = new_meeting(seeded)
    rows = seeded.insert_extracted_tasks(mid, [
        item(title="Mystery", seat="Chief Wizard", deadline="sometime soon"),
        item(title="Fine", seat="Treasurer", deadline="tomorrow"),
        item(title="Flagged", seat="Treasurer", needs_review=True),
    ])  # fmt: skip
    meeting = seeded.get_meeting(mid)
    assert meeting
    flags = {t["title"]: t["needs_review"] for t in meeting["tasks"]}
    assert flags == {"Mystery": True, "Fine": False, "Flagged": True}
    assert rows[0]["owner_code"] is None and rows[0]["due_date"] is None


def test_ambiguous_assignee_is_not_guessed(seeded: Repository):
    seeded.add_member("BOBS", "Bob Smith")
    mid = new_meeting(seeded)
    (row,) = seeded.insert_extracted_tasks(mid, [item(assignee="Bob")])
    assert row["owner_code"] is None
    meeting = seeded.get_meeting(mid)
    assert meeting and meeting["tasks"][0]["needs_review"] is True


def test_person_mode_uses_person_code(db_url: str):
    pool = make_pool(db_url)
    try:
        repo = Repository(pool, "person")
        repo.add_member("BOBN", "Bob Newman")
        mid = new_meeting(repo)
        (row,) = repo.insert_extracted_tasks(mid, [item(assignee="Bob")])
        assert row["owner_code"] == "BOBN"
    finally:
        pool.close()


def test_insert_extracted_tasks_is_idempotent_per_meeting(seeded: Repository):
    mid = new_meeting(seeded)
    first = seeded.insert_extracted_tasks(mid, [item(title="One"), item(title="Two")])
    again = seeded.insert_extracted_tasks(mid, [item(title="One"), item(title="Two")])
    assert {r["id"] for r in first} == {r["id"] for r in again}
    assert count(seeded, "tasks") == 4  # 2 fixture + 2 new
    assert count(seeded, "task_meeting_links") == 2


def test_insert_extracted_tasks_unknown_meeting_rolls_back(seeded: Repository):
    with pytest.raises(LookupError):
        seeded.insert_extracted_tasks(9999, [item()])
    assert count(seeded, "tasks") == 2


def test_long_title_truncated_to_column_limit(seeded: Repository):
    mid = new_meeting(seeded)
    (row,) = seeded.insert_extracted_tasks(mid, [item(title="x" * 500)])
    assert len(row["title"]) == 200


def test_many_tasks_get_unique_codes(seeded: Repository):
    mid = new_meeting(seeded)
    rows = seeded.insert_extracted_tasks(mid, [item(title=f"t{i}") for i in range(12)])
    assert len({r["task_code"] for r in rows}) == 12


def test_task_code_generation_survives_collisions(db_url: str):
    """With the DB trigger absent, a taken code is skipped (retry on unique violation)."""
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("drop trigger task_fields on public.tasks")
        c.execute("insert into public.tasks (task_code, title, month_code) values "
                  "('WIN-202611-1', 'taken', '2026-11'), ('WIN-202611-2', 'taken', '2026-11')")  # fmt: skip
    pool = make_pool(db_url)
    try:
        row = Repository(pool).add_task(title="new", month_code="2026-11")
        assert row["task_code"] == "WIN-202611-3"
    finally:
        pool.close()


# ---- list / update / dependencies
def test_list_tasks_filters(seeded: Repository):
    mid = new_meeting(seeded)
    seeded.insert_extracted_tasks(mid, [item(title="A", seat="Treasurer", deadline="tomorrow"),
                                        item(title="B", seat="Secretary")])  # fmt: skip
    assert len(seeded.list_tasks()) == 4
    # the synthetic fixture row "Order pizza for kickoff" is also owned by TREAS
    assert {t["title"] for t in seeded.list_tasks(owner_code="TREAS")} == {
        "A", "Order pizza for kickoff"}
    assert {t["title"] for t in seeded.list_tasks(owner_code="SEC")} == {"B"}
    assert len(seeded.list_tasks(source="meeting")) == 2
    assert len(seeded.list_tasks(meeting_id=mid)) == 2
    assert len(seeded.list_tasks(month_code="2026-10")) == 2  # the fixture rows
    assert len(seeded.list_tasks(status="done")) == 1
    due = seeded.list_tasks(due_before=date(2026, 11, 14), meeting_id=mid)
    assert {t["title"] for t in due} == {"A"}
    assert len(seeded.list_tasks(limit=1)) == 1


def test_update_task_by_code_and_uuid(seeded: Repository):
    row = seeded.add_task(title="Edit me", month_code="2026-11")
    updated = seeded.update_task(row["task_code"], status="in_progress", owner_code="SEC")
    assert (updated["status"], updated["owner_code"]) == ("in_progress", "SEC")
    assert updated["updated_at"] >= row["updated_at"]
    again = seeded.update_task(row["id"], title="Renamed", due_date=date(2026, 12, 1))
    assert again["title"] == "Renamed" and again["due_date"] == date(2026, 12, 1)
    assert seeded.update_task(str(row["id"]), tags=["x"])["tags"] == ["x"]


def test_update_task_rejects_bad_input_and_touches_one_row(seeded: Repository):
    row = seeded.add_task(title="Solo", month_code="2026-11")
    with pytest.raises(ValueError):
        seeded.update_task(row["task_code"], status="nonsense")
    with pytest.raises(ValueError):
        seeded.update_task(row["task_code"], task_code="HACK")  # immutable / not whitelisted
    with pytest.raises(ValueError):
        seeded.update_task(row["task_code"])
    with pytest.raises(LookupError):
        seeded.update_task("WIN-999999-1", status="done")
    seeded.update_task(row["task_code"], status="done")
    statuses = sorted(t["status"] for t in seeded.list_tasks())
    assert statuses == ["done", "done", "todo"]  # fixture: todo + done; plus ours (done)


def test_add_dependency(seeded: Repository):
    a = seeded.add_task(title="A", month_code="2026-11")["id"]
    b = seeded.add_task(title="B", month_code="2026-11")["id"]
    c = seeded.add_task(title="C", month_code="2026-11")["id"]
    seeded.add_dependency(a, b)
    seeded.add_dependency(a, b)  # idempotent
    seeded.add_dependency(b, c)
    assert count(seeded, "task_dependencies") == 2
    with pytest.raises(ValueError):
        seeded.add_dependency(a, a)
    with pytest.raises(ValueError):  # c -> a would close the loop a->b->c->a
        seeded.add_dependency(c, a)
