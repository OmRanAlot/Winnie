"""Migration tests against a real (throwaway) Postgres: the existing tables are untouched, the new
constraints behave, and re-applying is harmless."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from conftest import MIGRATIONS, apply_sql
from psycopg import errors
from psycopg.rows import dict_row

EXISTING = ("tasks", "tasks_placeholder")
NEW_TABLES = ("members", "meetings", "meeting_attendees", "transcript_segments",
              "task_meeting_links", "task_dependencies")  # fmt: skip


def snapshot(conn: psycopg.Connection[Any], tables: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in tables:
        out[t] = {
            "columns": conn.execute(
                "select column_name, data_type, is_nullable, column_default, is_generated "
                "from information_schema.columns where table_schema='public' and table_name=%s "
                "order by ordinal_position", (t,)).fetchall(),
            "constraints": conn.execute(
                "select conname, pg_get_constraintdef(oid) d from pg_constraint "
                "where conrelid = %s::regclass order by conname", (f"public.{t}",)).fetchall(),
            "indexes": conn.execute(
                "select indexdef from pg_indexes where schemaname='public' and tablename=%s "
                "order by indexname", (t,)).fetchall(),
            "triggers": conn.execute(
                "select tgname from pg_trigger where tgrelid=%s::regclass and not tgisinternal "
                "order by tgname", (f"public.{t}",)).fetchall(),
            "rls": conn.execute(
                "select relrowsecurity from pg_class where oid=%s::regclass",
                (f"public.{t}",)).fetchone(),
            "rows": conn.execute(f"select md5(string_agg(x::text, '|' order by x::text)), count(*) "
                                 f"from public.{t} x").fetchone(),
        }  # fmt: skip
    return out


def test_migrations_exist():
    assert len(MIGRATIONS) == 3


def test_existing_tables_unchanged_and_reapply_is_harmless(fixture_only_db_url: str):
    with psycopg.connect(fixture_only_db_url, autocommit=True, row_factory=dict_row) as c:
        before = snapshot(c, EXISTING)
        assert before["tasks"]["rows"]["count"] == 2
        for m in MIGRATIONS:
            apply_sql(fixture_only_db_url, m)
        after_first = snapshot(c, EXISTING)
        new_first = snapshot(c, NEW_TABLES)
        for m in MIGRATIONS:  # apply everything a second time
            apply_sql(fixture_only_db_url, m)
        after_second = snapshot(c, EXISTING)
        new_second = snapshot(c, NEW_TABLES)
    assert after_first == before
    assert after_second == before
    assert new_second == new_first


def test_rls_enabled_on_every_new_table(conn: psycopg.Connection[Any]):
    for t in NEW_TABLES:
        row = conn.execute("select relrowsecurity r from pg_class where oid=%s::regclass",
                           (f"public.{t}",)).fetchone()  # fmt: skip
        assert row and row["r"], t
    pols = conn.execute("select count(*) n from pg_policies where schemaname='public'").fetchone()
    assert pols and pols["n"] == 0


def test_anon_cannot_read_new_tables(conn: psycopg.Connection[Any]):
    for t in NEW_TABLES:
        has = conn.execute("select has_table_privilege('anon', %s, 'select') h",
                           (f"public.{t}",)).fetchone()  # fmt: skip
        assert has and has["h"] is False, t


def test_storage_bucket_guard_is_a_noop_on_plain_postgres(conn: psycopg.Connection[Any]):
    row = conn.execute("select to_regclass('storage.buckets') r").fetchone()
    assert row and row["r"] is None


def test_members_checks(conn: psycopg.Connection[Any]):
    conn.execute("insert into members (code, name) values ('SEC', 'Secretary')")
    row = conn.execute("select kind from members").fetchone()
    assert row and row["kind"] == "person"  # default
    with pytest.raises(errors.CheckViolation):
        conn.execute("insert into members (code, name, kind) values ('X', 'x', 'robot')")
    with pytest.raises(errors.CheckViolation):
        conn.execute("insert into members (code, name) values ('lower', 'x')")
    with pytest.raises(errors.UniqueViolation):
        conn.execute("insert into members (code, name) values ('SEC', 'dup')")


def make_meeting(conn: psycopg.Connection[Any], sha: str = "a") -> int:
    row = conn.execute("insert into meetings (held_at, audio_sha256) values (now(), %s) "
                       "returning id", (sha,)).fetchone()  # fmt: skip
    assert row
    return int(row["id"])


def scalar(conn: psycopg.Connection[Any], sql: str, *params: Any) -> Any:
    row = conn.execute(sql, params).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return next(iter(row.values()))


def test_meetings_defaults_checks_and_unique_sha(conn: psycopg.Connection[Any]):
    mid = make_meeting(conn)
    row = conn.execute("select status, audio_bucket, error from meetings where id=%s",
                       (mid,)).fetchone()  # fmt: skip
    assert row == {"status": "uploaded", "audio_bucket": "meeting-audio", "error": None}
    with pytest.raises(errors.UniqueViolation):
        make_meeting(conn)
    with pytest.raises(errors.CheckViolation):
        conn.execute("update meetings set status='bogus' where id=%s", (mid,))
    for status in ("transcribing", "summarizing", "extracting_tasks", "done", "failed"):
        conn.execute("update meetings set status=%s where id=%s", (status, mid))


def test_meetings_updated_at_trigger_and_tsvector(conn: psycopg.Connection[Any]):
    mid = make_meeting(conn)
    before = scalar(conn, "select updated_at from meetings where id=%s", mid)
    conn.execute("select pg_sleep(0.01)")
    conn.execute("update meetings set transcript_text='the treasurer orders pizza' where id=%s",
                 (mid,))  # fmt: skip
    assert scalar(conn, "select updated_at from meetings where id=%s", mid) > before
    assert scalar(conn, "select transcript_tsv @@ to_tsquery('english','pizza') from meetings "
                        "where id=%s", mid)  # fmt: skip


def test_segments_unique_and_cascade(conn: psycopg.Connection[Any]):
    mid = make_meeting(conn)
    conn.execute("insert into transcript_segments (meeting_id, idx, text) values (%s,0,'hi')", (mid,))
    with pytest.raises(errors.UniqueViolation):
        conn.execute("insert into transcript_segments (meeting_id, idx, text) values (%s,0,'x')",
                     (mid,))  # fmt: skip
    with pytest.raises(errors.NotNullViolation):
        conn.execute("insert into transcript_segments (meeting_id, idx, text) values (%s,1,null)",
                     (mid,))  # fmt: skip
    conn.execute("delete from meetings where id=%s", (mid,))
    assert scalar(conn, "select count(*) from transcript_segments") == 0


def test_attendee_and_link_cascades(conn: psycopg.Connection[Any]):
    mid = make_meeting(conn)
    member_id = scalar(conn, "insert into members (code, name) values ('A','A') returning id")
    conn.execute("insert into meeting_attendees values (%s,%s)", (mid, member_id))
    with pytest.raises(errors.UniqueViolation):
        conn.execute("insert into meeting_attendees values (%s,%s)", (mid, member_id))
    task_id = scalar(conn, "select id from tasks limit 1")
    conn.execute("insert into task_meeting_links (task_id, meeting_id, needs_review) "
                 "values (%s,%s,true)", (task_id, mid))  # fmt: skip
    with pytest.raises(errors.UniqueViolation):
        conn.execute("insert into task_meeting_links (task_id, meeting_id) values (%s,%s)",
                     (task_id, mid))  # fmt: skip
    conn.execute("delete from meetings where id=%s", (mid,))
    assert scalar(conn, "select count(*) from meeting_attendees") == 0
    assert scalar(conn, "select count(*) from task_meeting_links") == 0
    assert scalar(conn, "select count(*) from tasks") == 2  # tasks survive


def test_deleting_a_task_cascades_to_links_and_dependencies(conn: psycopg.Connection[Any]):
    mid = make_meeting(conn)
    a, b = (r["id"] for r in conn.execute("select id from tasks order by task_code").fetchall())
    conn.execute("insert into task_meeting_links (task_id, meeting_id) values (%s,%s)", (a, mid))
    conn.execute("insert into task_dependencies values (%s,%s)", (a, b))
    conn.execute("delete from tasks where id=%s", (a,))
    assert scalar(conn, "select count(*) from task_meeting_links") == 0
    assert scalar(conn, "select count(*) from task_dependencies") == 0


def test_self_dependency_rejected(conn: psycopg.Connection[Any]):
    a = scalar(conn, "select id from tasks limit 1")
    with pytest.raises(errors.CheckViolation):
        conn.execute("insert into task_dependencies values (%s,%s)", (a, a))


def test_dependency_requires_existing_tasks(conn: psycopg.Connection[Any]):
    a = scalar(conn, "select id from tasks limit 1")
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("insert into task_dependencies values (%s, gen_random_uuid())", (a,))


def test_meetings_guard_rejects_older_incompatible_table(fixture_only_db_url: str):
    with psycopg.connect(fixture_only_db_url, autocommit=True) as c:
        c.execute("create table public.meetings (id bigint primary key, held_at timestamptz)")
    with pytest.raises(errors.RaiseException):
        apply_sql(fixture_only_db_url, MIGRATIONS[1])


def test_fk_indexes_exist(conn: psycopg.Connection[Any]):
    names = {r["indexname"] for r in conn.execute(
        "select indexname from pg_indexes where schemaname='public'").fetchall()}  # fmt: skip
    for expected in ("meetings_held_at_idx", "meetings_transcript_tsv_idx",
                     "meeting_attendees_member_id_idx", "transcript_segments_member_id_idx",
                     "task_meeting_links_meeting_id_idx", "task_dependencies_depends_on_id_idx"):  # fmt: skip
        assert expected in names
