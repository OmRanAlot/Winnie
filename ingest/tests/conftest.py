"""Shared fixtures: an embedded throwaway Postgres (pgserver), a template DB per layer, and a
fresh database cloned from the template for every test (so tests never see each other's rows)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app.db import make_pool
from app.repository import Repository

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_SQL = ROOT / "tests" / "fixtures" / "existing_schema.sql"
MIGRATIONS = sorted((ROOT.parent / "supabase" / "migrations").glob("20261115*.sql"))


def apply_sql(url: str, path: Path) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(path.read_text(encoding="utf-8"))  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def pg_admin_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    import pgserver

    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="stop")
    yield server.get_uri()
    server.cleanup()


def _create_db(admin_url: str, name: str, template: str | None = None) -> str:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        suffix = f' template "{template}"' if template else ""
        conn.execute(f'create database "{name}"{suffix}')  # type: ignore[arg-type]
    return make_conninfo(admin_url, dbname=name)


@pytest.fixture(scope="session")
def fixture_template(pg_admin_url: str) -> str:
    """Template DB: just the pre-existing schema (two tables + synthetic rows)."""
    url = _create_db(pg_admin_url, "tmpl_fixture")
    apply_sql(url, FIXTURE_SQL)
    return "tmpl_fixture"


@pytest.fixture(scope="session")
def migrated_template(pg_admin_url: str, fixture_template: str) -> str:
    """Template DB: existing schema + all new migrations."""
    url = _create_db(pg_admin_url, "tmpl_migrated", fixture_template)
    for migration in MIGRATIONS:
        apply_sql(url, migration)
    return "tmpl_migrated"


def _fresh(admin_url: str, template: str) -> Iterator[str]:
    name = f"t_{uuid.uuid4().hex[:12]}"
    yield _create_db(admin_url, name, template)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'drop database if exists "{name}" with (force)')  # type: ignore[arg-type]


@pytest.fixture
def db_url(pg_admin_url: str, migrated_template: str) -> Iterator[str]:
    yield from _fresh(pg_admin_url, migrated_template)


@pytest.fixture
def fixture_only_db_url(pg_admin_url: str, fixture_template: str) -> Iterator[str]:
    yield from _fresh(pg_admin_url, fixture_template)


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture
def repo(db_url: str) -> Iterator[Repository]:
    pool = make_pool(db_url, max_size=3)
    yield Repository(pool, "seat")
    pool.close()
