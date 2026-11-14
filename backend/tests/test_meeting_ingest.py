"""Tests for POST /api/meetings/ingest (routes/meetings.py, services/meeting_ingest.py).

Gemini and Supabase are replaced by fakes, so these run offline and free.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.db import repository
from app.main import app
from app.services import meeting_ingest, recordings, task_assignment
from tests.fake_supabase import FakeClient

URL = "/api/meetings/ingest"
AUDIO = b"fake-audio"
ROSTER = {"President": "Jane Doe", "Secretary": "Alice"}
TRANSCRIPT = "Jane will email the sponsors by Friday."
SUMMARY = "The board agreed Jane emails sponsors."
TASK = {
    "title": "Email sponsors", "description": "Send the prospectus", "seat": "President",
    "rationale": "Leads outreach", "deadline": "by Friday",
}  # fmt: skip


class FakeGemini:
    """First call (audio in a list) returns transcript + summary; the next returns tasks."""

    def __init__(self):
        self.calls = []
        self.raises = None
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self.generate_content))

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        if isinstance(kwargs["contents"], list):
            return SimpleNamespace(text=json.dumps({"transcript": TRANSCRIPT, "summary": SUMMARY}))
        return SimpleNamespace(text=json.dumps([TASK]))


@pytest.fixture
def gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(task_assignment, "gemini_client", lambda api_key: fake)
    monkeypatch.setattr(task_assignment, "load_eboard", lambda: ROSTER)
    return fake


@pytest.fixture
def db(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(repository, "get_client", lambda: fake)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, signed_in_member):
    monkeypatch.setattr(recordings, "RECORDINGS_DIR", tmp_path)
    app.dependency_overrides[task_assignment.get_settings] = lambda: Settings(
        GEMINI_API_KEY="test-key", GEMINI_MODEL="test-model", _env_file=None
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(client, content=AUDIO, content_type="audio/webm"):
    return client.post(
        URL,
        files={"file": ("meeting.webm", content, content_type)},
        data={"title": "Board meeting", "held_at": "2026-11-14T12:00:00"},
    )


def test_audio_becomes_transcript_summary_and_stored_tasks(client, gemini, db, tmp_path):
    response = upload(client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["transcript"] == TRANSCRIPT and data["summary"] == SUMMARY
    assert [task["title"] for task in data["tasks"]] == ["Email sponsors"]
    assert db.tables["meetings"][0]["summary"] == SUMMARY
    assert len(db.tables["tasks"]) == 1
    assert (tmp_path / f"{data['recording_id']}.webm").read_bytes() == AUDIO


def test_uploading_the_same_audio_twice_does_not_duplicate(client, gemini, db):
    upload(client)
    second = upload(client)

    assert second.json()["meta"]["already_stored"] is True
    assert len(db.tables["meetings"]) == 1 and len(db.tables["tasks"]) == 1


def test_non_audio_is_rejected_before_gemini(client, gemini, db):
    assert upload(client, content_type="text/plain").status_code == 415
    assert gemini.calls == []


def test_empty_and_oversized_audio_are_rejected(client, gemini, db, monkeypatch):
    assert upload(client, content=b"").status_code == 422
    monkeypatch.setattr(meeting_ingest, "MAX_AUDIO_BYTES", 4)
    assert upload(client).status_code == 413
    assert gemini.calls == []


def test_missing_gemini_key_returns_503(client, gemini, db):
    app.dependency_overrides[task_assignment.get_settings] = lambda: Settings(_env_file=None, GEMINI_API_KEY=None)
    assert upload(client).status_code == 503


def test_gemini_failure_returns_502(client, gemini, db):
    gemini.raises = ValueError("blocked")
    assert upload(client).status_code == 502
    assert db.tables["meetings"] == []
