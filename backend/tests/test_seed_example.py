"""Tests for scripts/seed_example.py against the in-memory FakeClient."""

from app import repository
from scripts import seed_example
from tests.fake_supabase import FakeClient


def test_seed_inserts_three_tasks_once_and_prints_them(monkeypatch, capsys):
    fake = FakeClient()
    monkeypatch.setattr(repository, "get_client", lambda: fake)
    monkeypatch.setattr(seed_example, "get_client", lambda: fake)

    assert seed_example.main([]) == 0
    assert seed_example.main([]) == 0  # second run is skipped
    assert len(fake.tables["meetings"]) == 1
    assert len(fake.tables["tasks"]) == 3
    output = capsys.readouterr().out
    assert "Already seeded" in output
    assert "Check alternate room booking - Bob Newman (Vice President)" in output

    assert seed_example.main(["--force"]) == 0
    assert len(fake.tables["tasks"]) == 6
