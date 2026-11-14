"""psycopg3 connection pool (all repository access) plus a read-only connection for discovery."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool


def make_pool(db_url: str, *, min_size: int = 1, max_size: int = 4) -> ConnectionPool[Any]:
    """Open a pool. prepare_threshold=None keeps it compatible with Supabase's transaction-mode
    pooler (pgbouncer/supavisor), which does not support prepared statements."""
    pool: ConnectionPool[Any] = ConnectionPool(
        db_url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        open=False,
    )
    pool.open(wait=True, timeout=30)
    return pool


def readonly_connection(db_url: str) -> psycopg.Connection[DictRow]:
    """A connection that cannot write: the session default is read-only transactions.
    Used only by scripts/discover.py for SELECT-only introspection."""
    return psycopg.connect(
        db_url,
        row_factory=dict_row,
        options="-c default_transaction_read_only=on",
        autocommit=True,
    )
