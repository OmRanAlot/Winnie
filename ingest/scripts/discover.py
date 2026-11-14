"""READ-ONLY discovery of the real `tasks` table conventions.

Every session is opened with default_transaction_read_only=on and only SELECTs are issued.
Output goes to your terminal only; it may contain real task data, so do not commit it.

    SUPABASE_DB_URL=... python scripts/discover.py
"""

from __future__ import annotations

import os
import re
import sys

from app.db import readonly_connection

DISTINCT_COLUMNS = ("status", "month_code", "source", "event_tag", "owner_code")
LIMIT = 50


def main() -> int:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set; nothing verified against real data.", file=sys.stderr)
        return 1
    with readonly_connection(url) as conn:
        print("== columns")
        for r in conn.execute(
            "select column_name, data_type, is_nullable, column_default from information_schema.columns "
            "where table_schema='public' and table_name='tasks' order by ordinal_position"
        ):
            print(dict(r))
        print("== constraints")
        for r in conn.execute(
            "select conname, pg_get_constraintdef(oid) as def from pg_constraint "
            "where conrelid = 'public.tasks'::regclass"
        ):
            print(r["conname"], r["def"])
        print("== triggers")
        for r in conn.execute(
            "select tgname from pg_trigger where tgrelid = 'public.tasks'::regclass and not tgisinternal"
        ):
            print(r["tgname"])
        for col in DISTINCT_COLUMNS:  # column names come from the constant above, never user input
            rows = conn.execute(
                f"select {col} as v, count(*) as n from public.tasks group by 1 order by 2 desc limit {LIMIT}"  # type: ignore[arg-type]
            ).fetchall()
            print(f"== distinct {col}: {[(r['v'], r['n']) for r in rows]}")
        stakeholders = conn.execute(
            "select code, count(*) n from public.tasks, unnest(stakeholder_codes) code group by 1 "
            f"order by 2 desc limit {LIMIT}"  # type: ignore[arg-type]
        ).fetchall()
        print(f"== distinct stakeholder_codes: {[(r['code'], r['n']) for r in stakeholders]}")
        sample = conn.execute("select task_code from public.tasks order by created_at limit 5").fetchall()
        print(f"== task_code samples: {[r['task_code'] for r in sample]}")

        owners = conn.execute("select distinct owner_code v from public.tasks where owner_code is not null").fetchall()
        codes = [r["v"] for r in owners] + [r["code"] for r in stakeholders]
        short_role_like = [c for c in codes if re.fullmatch(r"[A-Z]{2,6}[0-9]?", c)]
        print(
            f"== heuristic: {len(short_role_like)}/{len(codes)} codes look like short role abbreviations "
            "(many => seats; names/initials => people; both => mixed). Decide, then set OWNER_CODE_KIND."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
