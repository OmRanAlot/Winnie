"""Local durable planning records and stage cache. No canonical task/member writes."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class RunNotFound(Exception):
    pass


class RunConflict(Exception):
    pass


class PlanningRunStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS planning_runs (
                    id TEXT PRIMARY KEY, request_json TEXT NOT NULL, context_json TEXT NOT NULL,
                    status TEXT NOT NULL, draft_json TEXT, revision TEXT, decision_json TEXT,
                    error_code TEXT, current_stage TEXT, lease_owner TEXT, lease_until REAL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planning_stage_results (
                    run_id TEXT NOT NULL, cache_key TEXT NOT NULL, stage TEXT NOT NULL,
                    result_json TEXT NOT NULL, PRIMARY KEY(run_id, cache_key)
                );
                CREATE TABLE IF NOT EXISTS planning_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    stage TEXT NOT NULL, action TEXT NOT NULL, created_at REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, request: dict, context: dict) -> str:
        run_id, now = str(uuid4()), time.time()
        with self.connect() as db:
            db.execute("INSERT INTO planning_runs(id,request_json,context_json,status,created_at,updated_at) VALUES(?,?,?,'queued',?,?)",
                       (run_id, json.dumps(request), json.dumps(context), now, now))
        return run_id

    def get(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM planning_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFound
        result = dict(row)
        for field in ("request", "context", "draft", "decision"):
            result[field] = json.loads(result.pop(f"{field}_json") or "null")
        return result

    def claim(self, run_id: str) -> str:
        """A bounded lease prevents duplicate generation/review across API processes."""
        owner, now = str(uuid4()), time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT lease_until FROM planning_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise RunNotFound
            if row["lease_until"] and row["lease_until"] > now:
                raise RunConflict("This planning run is already executing.")
            db.execute("UPDATE planning_runs SET lease_owner=?,lease_until=?,status='running',error_code=NULL,updated_at=? WHERE id=?",
                       (owner, now + 660, now, run_id))
        return owner

    def finish(self, run_id: str, owner: str, *, status: str, draft=None,
               revision=None, decision=None, error_code=None):
        with self.connect() as db:
            result = db.execute("""UPDATE planning_runs SET status=?,draft_json=COALESCE(?,draft_json),
                revision=COALESCE(?,revision),decision_json=COALESCE(?,decision_json),error_code=?,
                lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=? AND lease_owner=?""",
                (status, json.dumps(draft) if draft is not None else None, revision,
                 json.dumps(decision) if decision is not None else None, error_code,
                 time.time(), run_id, owner))
            if result.rowcount != 1:
                raise RunConflict("Planning run lease changed.")

    def event(self, run_id: str, stage: str, action: str):
        with self.connect() as db:
            db.execute("INSERT INTO planning_run_events(run_id,stage,action,created_at) VALUES(?,?,?,?)",
                       (run_id, stage, action, time.time()))
            db.execute("UPDATE planning_runs SET current_stage=?,updated_at=? WHERE id=?",
                       (stage, time.time(), run_id))

    def events(self, run_id: str):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT stage,action,created_at FROM planning_run_events WHERE run_id=? ORDER BY id", (run_id,))]

    def cached(self, run_id: str, key: str):
        with self.connect() as db:
            row = db.execute("SELECT result_json FROM planning_stage_results WHERE run_id=? AND cache_key=?",
                             (run_id, key)).fetchone()
        return row["result_json"] if row else None

    def cache(self, run_id: str, key: str, stage: str, result: str):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO planning_stage_results VALUES(?,?,?,?)",
                       (run_id, key, stage, result))

    def discard(self, run_id: str, key: str):
        with self.connect() as db:
            db.execute("DELETE FROM planning_stage_results WHERE run_id=? AND cache_key=?", (run_id, key))
