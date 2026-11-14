"""Pipeline end-to-end (fake transcriber + fake LLM + in-memory store, real throwaway Postgres),
plus the CLI run as a subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import ROOT

from app.deadlines import NEW_YORK
from app.llm import FakeLLM
from app.models import Segment
from app.pipeline import PipelineError, ingest_meeting
from app.repository import Repository
from app.storage import InMemoryAudioStore
from app.transcription import FakeTranscriber

HELD = datetime(2026, 11, 13, 18, 0, tzinfo=NEW_YORK)
SEGMENTS = [
    Segment(0, 0, 4000, "S1", "The Treasurer will order pizza by Monday noon."),
    Segment(1, 4000, 8000, None, "Bob will send the sponsor email tonight."),
]
EXTRACTION = json.dumps({"items": [
    {"title": "Order pizza", "description": "kickoff", "seat": "Treasurer", "assignee": None,
     "rationale": "said so", "deadline": "by Monday noon", "needs_review": False},
    {"title": "Send sponsor email", "seat": None, "assignee": "Bob", "deadline": "tonight"},
]})  # fmt: skip


def llm_reply(system: str, _messages: object) -> str:
    return EXTRACTION if "extract action items" in system else "- pizza\n- email"


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "sample.wav"
    path.write_bytes(b"RIFF....fake audio bytes")
    return path


@pytest.fixture
def seeded(repo: Repository) -> Repository:
    repo.add_member("TREAS", "Treasurer", "seat")
    repo.add_member("SEC", "Secretary", "seat")
    repo.add_member("BOBN", "Bob Newman", "person", seat="Secretary")
    return repo


def run(repo: Repository, audio: Path, *, transcriber: FakeTranscriber | None = None,
        llm: FakeLLM | None = None, store: InMemoryAudioStore | None = None,
        attendees: tuple[str, ...] = ("Bob", "Nobody")):  # fmt: skip
    return ingest_meeting(
        repo=repo, store=store or InMemoryAudioStore(),
        transcriber=transcriber or FakeTranscriber(SEGMENTS),
        llm=llm or FakeLLM([llm_reply]), audio_path=audio, title="Board", held_at=HELD,
        attendees=attendees, summary_model="sum-m", extraction_model="ext-m",
    )  # fmt: skip


def test_end_to_end(seeded: Repository, audio: Path):
    store = InMemoryAudioStore()
    result = run(seeded, audio, store=store)
    assert result.created and result.unresolved_attendees == ("Nobody",)
    meeting = seeded.get_meeting(result.meeting["id"])
    assert meeting
    assert meeting["status"] == "done" and meeting["error"] is None
    assert meeting["summary"] == "- pizza\n- email" and meeting["summary_model"] == "sum-m"
    assert meeting["transcription_model"] == "fake-transcriber"
    assert meeting["transcript_text"] == "\n".join(s.text for s in SEGMENTS)
    assert [s["idx"] for s in meeting["segments"]] == [0, 1]
    assert meeting["audio_bytes"] == audio.stat().st_size
    assert meeting["audio_mime"] in {"audio/x-wav", "audio/wav", "audio/vnd.wave"}
    assert meeting["audio_path"] in store.objects and meeting["audio_bucket"] == "meeting-audio"
    assert [m["code"] for m in meeting["attendees"]] == ["BOBN"]
    pizza, email = meeting["tasks"]
    assert (pizza["title"], pizza["owner_code"], pizza["due_date"]) == (
        "Order pizza", "TREAS", date(2026, 11, 16))
    assert (email["owner_code"], email["due_date"]) == ("SEC", date(2026, 11, 13))
    assert pizza["source"] == "meeting" and pizza["source_reference"] == f"meeting:{meeting['id']}"
    assert pizza["status"] == "todo" and pizza["month_code"] == "2026-11"
    assert len(seeded.list_tasks()) == 4  # 2 pre-existing fixture rows are untouched


def test_reingest_same_file_is_idempotent(seeded: Repository, audio: Path):
    store, transcriber, llm = InMemoryAudioStore(), FakeTranscriber(SEGMENTS), FakeLLM([llm_reply])
    first = run(seeded, audio, transcriber=transcriber, llm=llm, store=store)
    llm_calls = len(llm.calls)
    second = run(seeded, audio, transcriber=transcriber, llm=llm, store=store)
    assert not second.created and second.meeting["id"] == first.meeting["id"]
    assert (transcriber.calls, store.upload_calls, len(llm.calls)) == (1, 1, llm_calls)
    assert len(seeded.list_tasks()) == 4
    assert len(seeded.list_meetings()) == 1


def test_failure_mid_pipeline_is_recorded_and_rerun_resumes(seeded: Repository, audio: Path):
    transcriber = FakeTranscriber(SEGMENTS)
    store = InMemoryAudioStore()
    bad = FakeLLM([lambda s, m: "- summary ok" if "summarize" in s else "not json at all"])
    with pytest.raises(PipelineError) as exc:
        run(seeded, audio, transcriber=transcriber, llm=bad, store=store)
    assert exc.value.step == "extracting_tasks"
    (row,) = seeded.list_meetings()
    meeting = seeded.get_meeting(row["id"])
    assert meeting
    assert meeting["status"] == "failed" and "extracting_tasks" in meeting["error"]
    assert meeting["transcript_text"] and meeting["summary"] == "- summary ok"  # good steps kept
    assert seeded.list_tasks(source="meeting") == []

    good = FakeLLM([llm_reply])
    result = run(seeded, audio, transcriber=transcriber, llm=good, store=store)
    assert result.meeting["status"] == "done" and result.meeting["error"] is None
    assert transcriber.calls == 1 and store.upload_calls == 1  # did not redo transcription/upload
    assert all("extract action items" in c["system"] for c in good.calls)  # summary not redone
    assert len(seeded.list_tasks(source="meeting")) == 2


def test_transcription_failure_then_resume(seeded: Repository, audio: Path):
    transcriber = FakeTranscriber(SEGMENTS, fail_times=1)
    with pytest.raises(PipelineError) as exc:
        run(seeded, audio, transcriber=transcriber)
    assert exc.value.step == "transcribing"
    (row,) = seeded.list_meetings()
    assert row["status"] == "failed" and "transcribing" in row["error"]
    result = run(seeded, audio, transcriber=transcriber)
    assert result.meeting["status"] == "done" and not result.created


def test_missing_audio_file_raises_before_touching_db(seeded: Repository, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        run(seeded, tmp_path / "nope.wav")
    assert seeded.list_meetings() == []


def test_empty_transcription_fails_meeting(seeded: Repository, audio: Path):
    with pytest.raises(PipelineError):
        run(seeded, audio, transcriber=FakeTranscriber([]))
    (row,) = seeded.list_meetings()
    assert row["status"] == "failed"


# ---- CLI (subprocess, fakes via --dry-run-fakes)
def cli(db_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SUPABASE_DB_URL": db_url, "PYTHONIOENCODING": "utf-8"}
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    return subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)  # fmt: skip


def test_cli_end_to_end_with_fakes(db_url: str, audio: Path):
    assert cli(db_url, "members", "add", "--code", "TREAS", "--name", "Treasurer",
               "--kind", "seat").returncode == 0  # fmt: skip
    out = cli(db_url, "ingest", str(audio), "--title", "Board", "--held-at",
              "2026-11-13T18:00:00", "--dry-run-fakes")  # fmt: skip
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["created"] and data["meeting"]["status"] == "done"
    assert len(data["meeting"]["tasks"]) == 2
    mid = data["meeting"]["id"]
    again = json.loads(cli(db_url, "ingest", str(audio), "--held-at", "2026-11-13T18:00",
                           "--dry-run-fakes").stdout)  # fmt: skip
    assert again["created"] is False and again["meeting"]["id"] == mid
    assert json.loads(cli(db_url, "meetings", "list").stdout)[0]["id"] == mid
    assert json.loads(cli(db_url, "meetings", "show", str(mid)).stdout)["summary"]
    assert json.loads(cli(db_url, "search", "pizza").stdout)[0]["id"] == mid
    tasks = json.loads(cli(db_url, "tasks", "list", "--source", "meeting").stdout)
    assert len(tasks) == 2
    upd = cli(db_url, "tasks", "update", tasks[0]["task_code"], "--status", "done")
    assert json.loads(upd.stdout)["status"] == "done"
    added = json.loads(cli(db_url, "tasks", "add", "--title", "Manual", "--month", "2026-11").stdout)
    assert added["source"] == "manual" and added["status"] == "todo"
    members = json.loads(cli(db_url, "members", "list").stdout)
    assert [m["code"] for m in members] == ["TREAS"]


def test_cli_reports_errors_cleanly(db_url: str):
    assert cli(db_url, "meetings", "show", "999").returncode == 1
    bad = cli(db_url, "tasks", "update", "WIN-000000-1", "--status", "done")
    assert bad.returncode == 1 and "not found" in bad.stderr


def test_cli_missing_db_url_fails_loudly():
    env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL"}
    out = subprocess.run([sys.executable, "-m", "app.cli", "meetings", "list"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)  # fmt: skip
    assert out.returncode == 1 and "SUPABASE_DB_URL" in out.stderr
