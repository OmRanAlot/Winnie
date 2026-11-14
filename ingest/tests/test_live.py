"""Live smoke test. Skipped by default; run AFTER applying migrations:

    SUPABASE_DB_URL=... pytest -m live tests/test_live.py

Creates only rows it can identify as its own (a unique token) and deletes exactly those ids.
Note: tasks.source has a CHECK allowing only manual/meeting/sheet/doc/discord, so 'test-live' is
not insertable; rows are tagged with tags=['test-live'] and source_reference='test-live:<token>'."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest

from app.db import make_pool
from app.deadlines import NEW_YORK
from app.models import ExtractedTask
from app.repository import Repository

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.environ.get("SUPABASE_DB_URL"), reason="SUPABASE_DB_URL not set")
def test_live_smoke_roundtrip() -> None:
    token = uuid.uuid4().hex
    pool = make_pool(os.environ["SUPABASE_DB_URL"], max_size=2)
    repo = Repository(pool)
    task_ids: list[object] = []
    meeting_id: int | None = None
    member_code = f"TESTLIVE_{token[:8].upper()}"
    try:
        member = repo.add_member(member_code, f"Test Live {token[:6]}", "seat")
        meeting, _ = repo.create_meeting(
            title="test-live", held_at=datetime.now(NEW_YORK), audio_path=None, audio_mime=None,
            audio_bytes=None, audio_sha256=f"test-live-{token}",
        )  # fmt: skip
        meeting_id = int(meeting["id"])
        rows = repo.insert_extracted_tasks(
            meeting_id, [ExtractedTask(title="live smoke", seat=member.name, deadline="tomorrow")]
        )
        task_ids += [r["id"] for r in rows]
        month = datetime.now(NEW_YORK).strftime("%Y-%m")
        manual = repo.add_task(title="live manual", month_code=month, tags=["test-live"],
                               source_reference=f"test-live:{token}")  # fmt: skip
        task_ids.append(manual["id"])
        assert repo.update_task(manual["id"], status="in_progress")["status"] == "in_progress"
        assert rows[0]["owner_code"] == member_code
    finally:
        with pool.connection() as conn:
            if task_ids:
                conn.execute("delete from public.tasks where id = any(%s::uuid[])",
                             ([str(t) for t in task_ids],))  # fmt: skip
            if meeting_id is not None:
                conn.execute("delete from public.meetings where id = %s", (meeting_id,))
            conn.execute("delete from public.members where code = %s", (member_code,))
        pool.close()
