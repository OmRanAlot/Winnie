"""Tests for the task store wiring: GET/PATCH /api/tasks, storing assignments after a recording,
and the Supabase credential check. Supabase is replaced by tests/fake_supabase.FakeClient."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.deadlines import NEW_YORK
from app.core.settings import Settings
from app.db import repository
from app.domain.models import ExtractedTask
from app.integrations import supabase_client
from app.integrations.supabase_client import SupabaseNotConfigured, require_credentials
from app.main import app
from app.services import meeting_tasks, task_assignment
from tests.fake_supabase import FakeClient

MEETING_AT = datetime(2026, 11, 13, 18, 0, tzinfo=NEW_YORK)


@pytest.fixture
def db(monkeypatch) -> FakeClient:
    fake = FakeClient()
    monkeypatch.setattr(repository, "get_client", lambda: fake)
    return fake


@pytest.fixture
def client(signed_in_member):
    with TestClient(app) as test_client:
        yield test_client


def seed(db: FakeClient) -> None:
    meeting_id = repository.create_meeting(MEETING_AT, "GBM", None, client=db)
    repository.insert_extracted_tasks(
        meeting_id,
        [
            ExtractedTask(title="Book room", seat="Vice President", assignee="Bob Newman", deadline="Monday noon"),
            ExtractedTask(title="Order snacks", seat="Treasurer", assignee="Sam", deadline="tonight"),
            ExtractedTask(title="Figure it out", seat="Unassigned", needs_review=True, deadline="soon"),
        ],
        client=db,
    )


def test_list_tasks_returns_timeline_views_in_time_order(client, db):
    seed(db)
    body = client.get("/api/tasks").json()
    assert body["success"] is True and body["meta"] == {"count": 3}
    snacks, room, unscheduled = body["data"]
    assert [snacks["title"], room["title"], unscheduled["title"]] == ["Order snacks", "Book room", "Figure it out"]
    assert room["assignee"] == "Bob Newman" and room["seat"] == "Vice President"
    assert room["start"] == "2026-11-13T18:00:00-05:00"
    assert room["end"] == "2026-11-16T12:00:00-05:00"
    assert unscheduled["end"] is None and unscheduled["assignee"] is None
    assert unscheduled["deadline_raw"] == "soon"


def test_list_tasks_filters_by_query_params(client, db):
    seed(db)
    titles = [t["title"] for t in client.get("/api/tasks", params={"assignee": "bob"}).json()["data"]]
    assert titles == ["Book room"]
    titles = [t["title"] for t in client.get("/api/tasks", params={"seat": "Treasurer"}).json()["data"]]
    assert titles == ["Order snacks"]


def test_list_tasks_rejects_unknown_status(client, db):
    response = client.get("/api/tasks", params={"status": "finished"})
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_patch_status_checks_off_a_task(client, db):
    seed(db)
    task_id = db.tables["tasks"][0]["id"]
    response = client.patch(f"/api/tasks/{task_id}/status", json={"status": "done"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "done"
    assert [t["id"] for t in client.get("/api/tasks", params={"status": "done"}).json()["data"]] == [task_id]


def test_patch_status_errors(client, db):
    assert client.patch("/api/tasks/00000000-0000-4000-8000-000000000099/status", json={"status": "done"}).status_code == 404
    assert client.patch("/api/tasks/1/status", json={"status": "finished"}).status_code == 422


def test_record_api_and_timeline_share_ingested_uuid_tasks(client, db):
    from app.routes.tasks import authorize_tasks, get_task_store
    from app.services.tasks import TaskStore

    seed(db)
    db.postgrest = SimpleNamespace(session=SimpleNamespace(close=lambda: None))
    app.dependency_overrides[get_task_store] = lambda: TaskStore(lambda: db)
    app.dependency_overrides[authorize_tasks] = lambda: None
    try:
        response = client.get("/api/tasks/records", params={"limit": 1})
        assert response.status_code == 200
        records = response.json()
        assert records["meta"]["total"] == 3 and len(records["data"]) == 1
        task_id = records["data"][0]["id"]
        assert records["data"][0]["month_code"] == "2026-11"
        changed = client.patch(f"/api/tasks/records/{task_id}", json={"status": "in_progress"})
        assert changed.status_code == 200
        [view] = client.get("/api/tasks", params={"status": "in_progress"}).json()["data"]
        assert view["id"] == task_id
        client.patch(f"/api/tasks/{task_id}/status", json={"status": "done"})
        assert client.get(f"/api/tasks/records/{task_id}").json()["data"]["status"] == "done"
    finally:
        app.dependency_overrides.pop(get_task_store, None)
        app.dependency_overrides.pop(authorize_tasks, None)


def test_dependency_batch_endpoint_persists_only_admin_validated_links(client, db):
    from app.core.auth import require_admin
    from app.routes.tasks import authorize_tasks

    seed(db)
    task_ids = [task["id"] for task in db.tables["tasks"]]
    app.dependency_overrides[authorize_tasks] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    try:
        body = {"edges": [
            {"task_id": task_ids[0], "depends_on_id": task_ids[1]},
            {"task_id": task_ids[1], "depends_on_id": task_ids[2]},
        ]}
        response = client.post("/api/tasks/records/dependencies", json=body)
        assert response.status_code == 200
        assert response.json()["data"]["added"] == 2
        assert len(db.tables["task_dependencies"]) == 2

        repeated = client.post("/api/tasks/records/dependencies", json=body)
        assert repeated.status_code == 200
        assert repeated.json()["data"]["added"] == 0

        cycle = client.post("/api/tasks/records/dependencies", json={"edges": [
            {"task_id": task_ids[2], "depends_on_id": task_ids[0]},
        ]})
        assert cycle.status_code == 422
        assert len(db.tables["task_dependencies"]) == 2
    finally:
        app.dependency_overrides.pop(authorize_tasks, None)
        app.dependency_overrides.pop(require_admin, None)


def test_unconfigured_store_returns_503(client, monkeypatch):
    def not_configured():
        raise SupabaseNotConfigured("Missing SUPABASE_URL")

    monkeypatch.setattr(repository, "get_client", not_configured)
    response = client.get("/api/tasks")
    assert response.status_code == 503
    assert "task store" in response.json()["error"]["message"]


# --- every new assignment run is stored ---------------------------------------------------------


def fake_recording_flow(monkeypatch) -> None:
    recording = SimpleNamespace(
        startedAt=MEETING_AT, title="E-board sync", transcription=SimpleNamespace(text="Bob books the room.")
    )
    monkeypatch.setattr(meeting_tasks.recordings, "load_recording", lambda _id: recording)

    async def assign(_body, _settings):
        assignment = ExtractedTask(title="Book room", seat="Vice President", assignee="Bob Newman",
                                   rationale="Bob offered.", deadline="by Monday noon")
        return {"success": True, "data": {"assignments": [assignment.model_dump()]}, "error": None,
                "meta": {"count": 1, "needs_review": 0}}

    monkeypatch.setattr(task_assignment, "assign_tasks", assign)


def run_flow() -> dict:
    settings = SimpleNamespace(task_transcript_source="recording")
    return asyncio.run(meeting_tasks.assign_for_recording("rec", settings))


def test_assignments_are_stored_as_tasks(db, monkeypatch):
    fake_recording_flow(monkeypatch)
    response = run_flow()
    assert response["meta"]["stored"] is True
    [task] = response["data"]["tasks"]
    assert task["end"] == "2026-11-16T12:00:00-05:00"
    [meeting] = db.tables["meetings"]
    assert meeting["title"] == "E-board sync" and meeting["transcript"] == "Bob books the room."
    assert [row["title"] for row in db.tables["tasks"]] == ["Book room"]
    assert response["meta"]["already_stored"] is False


def test_retrying_a_recording_does_not_duplicate_tasks(db, monkeypatch):
    fake_recording_flow(monkeypatch)
    run_flow()
    retry = run_flow()
    assert retry["meta"]["stored"] is True and retry["meta"]["already_stored"] is True
    assert [t["title"] for t in retry["data"]["tasks"]] == ["Book room"]
    assert len(db.tables["meetings"]) == 1 and len(db.tables["tasks"]) == 1


def test_retry_fills_a_meeting_whose_task_insert_failed(db, monkeypatch):
    fake_recording_flow(monkeypatch)
    repository.create_meeting(MEETING_AT, "E-board sync", None, client=db, recording_id="rec")
    response = run_flow()
    assert response["meta"]["already_stored"] is False
    assert len(db.tables["meetings"]) == 1 and len(db.tables["tasks"]) == 1


def test_storage_failure_still_returns_assignments(monkeypatch):
    fake_recording_flow(monkeypatch)

    def not_configured():
        raise SupabaseNotConfigured("Missing SUPABASE_URL")

    monkeypatch.setattr(repository, "get_client", not_configured)
    response = run_flow()
    assert response["meta"]["stored"] is False
    assert response["meta"]["store_error"]
    assert len(response["data"]["assignments"]) == 1


# --- credentials ----------------------------------------------------------------------------------


@pytest.mark.parametrize("variable", [
    "SUPABASE_SECRET_KEY", "WINNIE_SUPABASE_SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY", "WINNIE_SUPABASE_SERVICE_ROLE_KEY",
])
def test_backend_key_environment_aliases(monkeypatch, variable):
    for name in (
        "SUPABASE_SECRET_KEY", "WINNIE_SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY", "WINNIE_SUPABASE_SERVICE_ROLE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, "sb_secret_synthetic")
    settings = Settings(SUPABASE_URL="https://x.supabase.co", _env_file=None)
    assert require_credentials(settings) == ("https://x.supabase.co", "sb_secret_synthetic")
    assert "sb_secret_synthetic" not in repr(settings)


def test_secret_key_from_dotenv_takes_precedence_over_legacy_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SUPABASE_URL=https://x.supabase.co\n"
        "SUPABASE_SECRET_KEY=sb_secret_synthetic\nSUPABASE_SERVICE_ROLE_KEY=\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert require_credentials(settings) == ("https://x.supabase.co", "sb_secret_synthetic")


def test_missing_credentials_fail_loudly_without_leaking_values():
    with pytest.raises(SupabaseNotConfigured) as error:
        require_credentials(Settings(supabase_url=None, supabase_service_role_key=None))
    assert "SUPABASE_URL" in str(error.value) and "SUPABASE_SERVICE_ROLE_KEY" in str(error.value)

    settings = Settings(supabase_url="https://x.supabase.co", supabase_service_role_key=SecretStr(""))
    with pytest.raises(SupabaseNotConfigured, match="SUPABASE_SERVICE_ROLE_KEY"):
        require_credentials(settings)


def test_credentials_are_returned_and_key_is_not_in_repr():
    settings = Settings(supabase_url="https://x.supabase.co", supabase_service_role_key=SecretStr("sekret"))
    assert require_credentials(settings) == ("https://x.supabase.co", "sekret")
    assert "sekret" not in repr(settings)


def test_get_client_is_a_singleton(monkeypatch):
    supabase_client.get_client.cache_clear()
    created = []
    monkeypatch.setattr(supabase_client, "require_credentials", lambda _s: ("https://x.supabase.co", "k"))
    monkeypatch.setattr(supabase_client, "create_client", lambda url, key: created.append(url) or object())
    try:
        assert supabase_client.get_client() is supabase_client.get_client()
        assert created == ["https://x.supabase.co"]
    finally:
        supabase_client.get_client.cache_clear()
