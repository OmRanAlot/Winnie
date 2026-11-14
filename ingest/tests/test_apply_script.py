"""scripts/apply_migrations.sh against the throwaway Postgres.

Regression: with some psql builds, options placed after the connection string are silently ignored,
so the script once 'succeeded' while applying nothing. This test checks the tables really appear."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import psycopg
import pytest
from conftest import ROOT

LOCATIONS = (r"C:\Program Files\Git\usr\bin\bash.exe", "/bin/bash", "/usr/bin/bash")


def find_bash() -> str | None:
    for candidate in LOCATIONS:
        if Path(candidate).exists():
            return candidate
    return shutil.which("bash")


def find_psql() -> Path | None:
    import pgserver

    exe = "psql.exe" if os.name == "nt" else "psql"
    path = Path(pgserver.__file__).parent / "pginstall" / "bin" / exe
    return path if path.exists() else None


def run_script(bash: str, url: str, psql_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SUPABASE_DB_URL": url, "PATH": f"{psql_dir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([bash, "scripts/apply_migrations.sh", "--yes"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)  # fmt: skip


def test_apply_script_applies_records_and_is_rerunnable(fixture_only_db_url: str):
    bash, psql = find_bash(), find_psql()
    if bash is None or psql is None:
        pytest.skip("needs bash and a psql binary (pgserver ships one)")
    first = run_script(bash, fixture_only_db_url, psql.parent)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "ignored" not in first.stderr  # no 'extra command-line argument ignored' warnings
    with psycopg.connect(fixture_only_db_url) as c:
        tables = {r[0] for r in c.execute(
            "select table_name from information_schema.tables where table_schema='public'")}
        assert {"members", "meetings", "task_meeting_links", "task_dependencies"} <= tables
        assert c.execute("select count(*) from public.ingest_migrations").fetchone() == (3,)
    second = run_script(bash, fixture_only_db_url, psql.parent)
    assert second.returncode == 0 and "already applied" in second.stdout
    assert "password" not in first.stdout.lower()


def test_apply_script_requires_db_url():
    bash = find_bash()
    if bash is None:
        pytest.skip("needs bash")
    env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL"}
    out = subprocess.run([bash, "scripts/apply_migrations.sh", "--yes"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)  # fmt: skip
    assert out.returncode != 0 and "SUPABASE_DB_URL" in out.stderr
