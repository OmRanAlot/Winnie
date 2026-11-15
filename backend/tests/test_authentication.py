"""Verify real HTTP authorization boundaries with synthetic Auth and roster records."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.settings import Settings
from app.main import app

USER_ID = "11111111-1111-4111-8111-111111111111"
USER = {"id": USER_ID, "email": "alice@example.com", "email_confirmed_at": "2026-11-14T12:00:00Z",
        "user_metadata": {"is_admin": True}}
PROFILE = {"id": USER_ID, "email": "alice@example.com", "member_code": "ALICE",
           "name": "Alice", "role": "Treasurer", "is_admin": False, "password_setup_complete": True}
MEMBER = {"code": "ALICE", "email": "alice@example.com", "active": True, "contact_consent": True}


@pytest.fixture
def signed_token(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda token, settings: dict(USER))
    monkeypatch.setattr(auth, "load_profile", lambda user: dict(PROFILE))
    return {"Authorization": "Bearer synthetic-token"}


@pytest.mark.parametrize("path,method", [
    ("/api/tasks", "get"), ("/api/tasks/records", "get"), ("/api/members", "get"),
    ("/api/tasks/records/dependencies", "post"),
    ("/api/recordings", "post"), ("/api/meetings/ingest", "post"),
    ("/api/assign_task_from_gemini", "post"), ("/api/planning/drafts", "post"),
    ("/api/help-requests", "get"), ("/api/auth/me", "get"),
])
def test_anonymous_callers_cannot_read_or_mutate_board_data(monkeypatch, path, method):
    monkeypatch.setenv("WINNIE_TASK_API_KEY", "")
    with TestClient(app) as client:
        assert getattr(client, method)(path).status_code == 401


def test_invalid_bearer_never_falls_back_to_shared_key(monkeypatch):
    monkeypatch.setenv("WINNIE_TASK_API_KEY", "trusted-server-key")
    def reject(token, settings):
        raise auth.HTTPException(401, "Expired token")
    monkeypatch.setattr(auth, "verify_token", reject)
    with TestClient(app) as client:
        result = client.get("/api/tasks", headers={"Authorization": "Bearer invalid",
                                                   "X-Winnie-Api-Key": "trusted-server-key"})
        assert result.status_code == 401
        assert client.get("/api/auth/me", headers={"X-Winnie-Api-Key": "trusted-server-key"}).status_code == 401


def test_me_uses_private_profile_and_does_not_trust_user_metadata(signed_token):
    with TestClient(app) as client:
        profile = client.get("/api/auth/me", headers=signed_token).json()["data"]
        assert profile["role"] == "Treasurer" and profile["is_admin"] is False
        assert client.get("/api/help-requests", headers=signed_token).status_code == 403
        assert client.delete(f"/api/tasks/records/{USER_ID}", headers=signed_token).status_code == 403
        assert client.post("/api/tasks/records/dependencies", headers=signed_token, json={"edges": [
            {"task_id": USER_ID, "depends_on_id": "22222222-2222-4222-8222-222222222222"},
        ]}).status_code == 403
        assert client.post(f"/api/planning/runs/{USER_ID}/review", headers=signed_token,
                           json={"decision": "approve", "expected_revision": "0" * 64}).status_code == 403


def test_invited_member_can_load_profile_but_cannot_access_dashboard_before_password(monkeypatch, signed_token):
    monkeypatch.setattr(auth, "load_profile", lambda user: {**PROFILE, "password_setup_complete": False})
    with TestClient(app) as client:
        assert client.get("/api/auth/me", headers=signed_token).status_code == 200
        assert client.get("/api/tasks", headers=signed_token).status_code == 403


@pytest.mark.parametrize("profile,member", [
    ({**PROFILE, "member_code": None}, MEMBER),
    (PROFILE, {**MEMBER, "active": False}),
    (PROFILE, {**MEMBER, "contact_consent": False}),
    (PROFILE, {**MEMBER, "email": "other@example.com"}),
    ({**PROFILE, "email": "other@example.com"}, MEMBER),
])
def test_membership_requires_exact_approved_active_contact(monkeypatch, profile, member):
    class Query:
        def __init__(self, table):
            self.data = [profile] if table == "profiles" else [member]
        def select(self, *args): return self
        def eq(self, *args): return self
        def execute(self): return SimpleNamespace(data=self.data)
    client = SimpleNamespace(table=Query, postgrest=SimpleNamespace(session=SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(auth, "create_task_client", lambda: client)
    with pytest.raises(auth.HTTPException) as error:
        auth.load_profile(USER)
    assert error.value.status_code == 403


@pytest.mark.parametrize("status,body,expected", [
    (401, {}, 401), (503, {}, 503), (200, {**USER, "email_confirmed_at": None}, 403),
    (200, {"id": "invalid"}, 503),
])
def test_auth_server_failure_is_fail_closed(monkeypatch, status, body, expected):
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(
        status, json=body, request=httpx.Request("GET", "https://example.com/auth/v1/user")))
    settings = Settings(supabase_url="https://example.com", supabase_service_role_key="synthetic")
    with pytest.raises(auth.HTTPException) as error:
        auth.verify_token("synthetic-token", settings)
    assert error.value.status_code == expected


def test_cors_preflight_and_health_remain_available():
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.options("/api/tasks", headers={"Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}).status_code == 200
