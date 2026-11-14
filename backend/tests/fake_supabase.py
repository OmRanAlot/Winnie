"""In-memory stand-in for the slice of the supabase-py client that app/db/repository.py uses.

Supports table(...).select/insert/update/delete with .eq/.in_/.limit and .execute(). Mimics
the migration's identity ids, defaults, unique constraints (23505) and foreign keys (23503),
so repository logic is tested without a live Supabase project.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from postgrest.exceptions import APIError

DEFAULTS: dict[str, dict[str, Any]] = {
    "seats": {},
    "people": {"aliases": []},
    "meetings": {"title": None, "transcript": None, "recording_id": None, "summary": None},
    "tasks": {
        "description": None, "seat_id": None, "assignee_id": None, "rationale": None,
        "deadline_raw": None, "deadline_at": None, "needs_review": False, "status": "open",
        "source_meeting_id": None, "raw_json": None,
    },
    "task_dependencies": {},
}  # fmt: skip
FOREIGN_KEYS = {
    "tasks": {"seat_id": "seats", "assignee_id": "people", "source_meeting_id": "meetings"},
    "task_dependencies": {"task_id": "tasks", "depends_on_id": "tasks"},
}


class FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {name: [] for name in DEFAULTS}
        self.next_id: dict[str, int] = {name: 1 for name in DEFAULTS}
        self.calls: list[tuple[str, str]] = []

    def table(self, name: str) -> Query:
        return Query(self, name)

    def unique_keys(self, table: str, row: dict[str, Any]) -> list[Any]:
        if table == "seats":
            return [row["name"]]
        if table == "people":
            return [row["name"].lower()]
        if table == "task_dependencies":
            return [(row["task_id"], row["depends_on_id"])]
        if table == "meetings" and row.get("recording_id") is not None:
            return [row["recording_id"]]
        return []

    def insert(self, table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        created = []
        for row in rows:
            new = {**copy.deepcopy(DEFAULTS[table]), **copy.deepcopy(row)}
            for column, target in FOREIGN_KEYS.get(table, {}).items():
                ref = new.get(column)
                if ref is not None and not any(r["id"] == ref for r in self.tables[target]):
                    raise APIError({"code": "23503", "message": f"{column} not present"})
            existing = {k for r in self.tables[table] for k in self.unique_keys(table, r)}
            if any(k in existing for k in self.unique_keys(table, new)):
                raise APIError({"code": "23505", "message": "duplicate key"})
            if table != "task_dependencies":
                new["id"] = self.next_id[table]
                self.next_id[table] += 1
            if table == "tasks":
                now = datetime.now(UTC).isoformat()
                new.setdefault("created_at", now)
                new.setdefault("updated_at", now)
            created.append(new)
        self.tables[table].extend(created)
        return copy.deepcopy(created)


class Query:
    def __init__(self, client: FakeClient, table: str) -> None:
        self.client, self.table = client, table
        self.op = "select"
        self.payload: Any = None
        self.filters: list[tuple[str, Any]] = []
        self.max_rows: int | None = None

    def select(self, *_columns: str) -> Query:
        self.op = "select"
        return self

    def insert(self, payload: dict | list[dict]) -> Query:
        self.op, self.payload = "insert", payload if isinstance(payload, list) else [payload]
        return self

    def update(self, payload: dict) -> Query:
        self.op, self.payload = "update", payload
        return self

    def delete(self) -> Query:
        self.op = "delete"
        return self

    def eq(self, column: str, value: Any) -> Query:
        self.filters.append((column, lambda v, value=value: v == value))
        return self

    def in_(self, column: str, values: list[Any]) -> Query:
        self.filters.append((column, lambda v, values=tuple(values): v in values))
        return self

    def limit(self, count: int) -> Query:
        self.max_rows = count
        return self

    def order(self, column: str, *, desc: bool = False, nullsfirst: bool | None = None) -> Query:
        self.order_by = (column, desc, bool(nullsfirst))
        return self

    def matches(self, row: dict[str, Any]) -> bool:
        return all(test(row.get(column)) for column, test in self.filters)

    def execute(self) -> SimpleNamespace:
        self.client.calls.append((self.table, self.op))
        rows = self.client.tables[self.table]
        if self.op == "insert":
            return SimpleNamespace(data=self.client.insert(self.table, self.payload))
        matched = [row for row in rows if self.matches(row)]
        if self.op == "update":
            for row in matched:
                row.update(copy.deepcopy(self.payload))
                if self.table == "tasks":
                    row["updated_at"] = datetime.now(UTC).isoformat()
        elif self.op == "delete":
            self.client.tables[self.table] = [row for row in rows if not self.matches(row)]
        if getattr(self, "order_by", None):
            column, desc, nulls_first = self.order_by
            present = sorted((r for r in matched if r.get(column) is not None),
                             key=lambda r: r[column], reverse=desc)
            missing = [r for r in matched if r.get(column) is None]
            matched = missing + present if nulls_first else present + missing
        if self.max_rows is not None:
            matched = matched[: self.max_rows]
        return SimpleNamespace(data=copy.deepcopy(matched))
