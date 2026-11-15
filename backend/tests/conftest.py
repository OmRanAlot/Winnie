"""Explicit signed-in fixtures for feature tests; auth tests exercise the real boundaries."""

import pytest

from app.core.auth import Principal, get_principal
from app.main import app


@pytest.fixture(autouse=True)
def isolated_conversation_memory(monkeypatch):
    """Existing unit tests never contact a live memory database; memory tests opt in."""
    monkeypatch.setenv('WINNIE_MESSAGE_MEMORY_ENABLED', 'false')


@pytest.fixture
def signed_in_member(monkeypatch):
    principal = Principal("11111111-1111-4111-8111-111111111111", {
        "member_code": "SYNTHETIC", "is_admin": True, "password_setup_complete": True,
    })
    monkeypatch.setitem(app.dependency_overrides, get_principal, lambda: principal)
    return principal
