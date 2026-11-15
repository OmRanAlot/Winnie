"""The serve CLI: prod behaviour unless --local is passed, and --local leaves no trace."""

import pytest

from app.cli import serve
from app.core.settings import Settings


@pytest.fixture
def run(monkeypatch):
    calls = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    # setenv-then-delenv registers the variable with monkeypatch, so whatever serve.main()
    # sets directly on os.environ is rolled back after each test.
    monkeypatch.setenv("WINNIE_MODE", "prod")
    monkeypatch.delenv("WINNIE_MODE")
    return calls


def test_default_is_prod_mode_on_all_interfaces_without_reload(run):
    serve.main([])

    (args, kwargs), = run
    assert args == ("app.main:app",)
    assert kwargs == {"host": "0.0.0.0", "port": 8000, "reload": False}
    assert Settings().mode == "prod"


def test_local_flag_sets_local_mode_binds_loopback_and_reloads(run):
    serve.main(["--local", "--port", "9000"])

    (_, kwargs), = run
    assert kwargs == {"host": "127.0.0.1", "port": 9000, "reload": True}
    assert Settings().mode == "local"
    assert Settings().is_local


def test_mode_defaults_to_prod_with_no_environment_set(monkeypatch):
    monkeypatch.delenv("WINNIE_MODE", raising=False)

    assert Settings().mode == "prod"
    assert not Settings().is_local
