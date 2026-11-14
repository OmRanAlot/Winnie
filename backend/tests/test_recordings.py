import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import recordings


@pytest.fixture
def client(tmp_path, monkeypatch, signed_in_member):
    monkeypatch.setattr(recordings, "RECORDINGS_DIR", tmp_path)
    with TestClient(app) as client:
        yield client


def payload():
    return {
        "schemaVersion": 1,
        "title": "Meeting",
        "startedAt": "2026-11-14T12:00:00Z",
        "durationMs": 1200,
        "transcription": {
            "text": "Hello Winnie",
            "language": "en-US",
            "provider": "browser-speech-recognition",
            "status": "completed",
        },
        "audio": {
            "mimeType": "audio/webm;codecs=opus",
            "encoding": "base64",
            "sizeBytes": 5,
            "data": base64.b64encode(b"audio").decode(),
        },
    }


def test_save_audio_and_browser_transcript(client, tmp_path):
    response = client.post("/api/recordings", json=payload())
    assert response.status_code == 201
    saved = json.loads((tmp_path / response.json()["data"]["filename"]).read_text())
    assert saved["transcription"]["text"] == "Hello Winnie"
    assert base64.b64decode(saved["audio"]["data"]) == b"audio"


def test_audio_is_saved_as_its_own_file(client, tmp_path):
    data = client.post("/api/recordings", json=payload()).json()["data"]
    assert data["audioFilename"].endswith(".webm")
    assert data["audioFilename"].removesuffix(".webm") == data["filename"].removesuffix(".json")
    assert (tmp_path / data["audioFilename"]).read_bytes() == b"audio"


@pytest.mark.parametrize(
    "field,value", [("data", "!bad!"), ("sizeBytes", 6), ("mimeType", "text/html")]
)
def test_invalid_audio_is_not_saved(client, tmp_path, field, value):
    body = payload()
    body["audio"][field] = value
    assert client.post("/api/recordings", json=body).status_code == 422
    assert not list(tmp_path.iterdir())


def test_missing_fields_and_non_json(client):
    assert client.post("/api/recordings", json={}).status_code == 422
    assert client.post("/api/recordings", content=b"x").status_code == 415


def test_body_limit(client, monkeypatch):
    monkeypatch.setattr("app.routes.recordings.MAX_JSON_BYTES", 10)
    assert client.post("/api/recordings", json=payload()).status_code == 413


def test_storage_failure(client, monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("app.routes.recordings.save_recording", fail)
    response = client.post("/api/recordings", json=payload())
    assert response.status_code == 503
    assert "download locally" in response.json()["error"]["message"]


def test_cors_allows_frontend_post(client):
    response = client.options(
        "/api/recordings",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
