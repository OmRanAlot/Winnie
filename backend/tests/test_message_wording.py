"""Natural wording is cosmetic: any doubt falls back to the original template."""

import json
from types import SimpleNamespace

import pytest

from app.agents.message_wording import reword

TEMPLATE = (
    'Winnie REQ-8: proposed task "Book room" (WIN-202610-1), due 2026-11-20. Open Requests to '
    "Accept/Deny, or text accept REQ-8 / deny REQ-8. Acceptance still requires admin approval."
)
GOOD = (
    "Hey! Someone suggested you take over \"Book room\" (WIN-202610-1), due 2026-11-20. "
    "Just reply accept REQ-8 or deny REQ-8. It still needs admin approval either way."
)


def config(**changes):
    return SimpleNamespace(**{
        "message_ai_enabled": True, "message_reword_enabled": True, "gemini_api_key": "fake",
        "gemini_model": "test-model", "message_ai_model": "", "message_ai_timeout_seconds": 5,
        **changes,
    })


def model(text):
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return json.dumps({"text": text})

    generate.calls = calls
    return generate


def test_a_faithful_friendlier_rewrite_is_used():
    generate = model(GOOD)
    assert reword(TEMPLATE, config(), generate=generate) == GOOD
    assert len(generate.calls) == 1


@pytest.mark.parametrize("bad", [
    GOOD.replace("WIN-202610-1", "WIN-202610-2"),  # wrong task code
    GOOD.replace("2026-11-20", "2026-11-21"),  # wrong date
    GOOD.replace("accept REQ-8 or deny REQ-8", "accept REQ-8 or deny REQ-9"),  # invented request
    GOOD.replace("It still needs admin approval either way.", "It is all set."),  # drops the safeguard
    GOOD + " More at https://example.com/x",
    GOOD + " " + "x" * 600,
    "",
])
def test_any_changed_fact_or_missing_safeguard_falls_back_to_the_template(bad):
    assert reword(TEMPLATE, config(), generate=model(bad)) == TEMPLATE


def test_model_failures_and_garbage_fall_back_silently():
    def explode(prompt):
        raise TimeoutError("slow")

    assert reword(TEMPLATE, config(), generate=explode) == TEMPLATE
    assert reword(TEMPLATE, config(), generate=lambda prompt: "not json") == TEMPLATE
    assert reword(TEMPLATE, config(), generate=lambda prompt: json.dumps({"other": 1})) == TEMPLATE


@pytest.mark.parametrize("changes", [
    {"message_reword_enabled": False},
    {"message_ai_enabled": False},
    {"gemini_api_key": None},
])
def test_disabled_or_unconfigured_never_calls_the_model(changes):
    generate = model(GOOD)
    assert reword(TEMPLATE, config(**changes), generate=generate) == TEMPLATE
    assert generate.calls == []


def test_reminder_delivery_text_is_reworded_on_the_way_out(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import reminders

    monkeypatch.setenv("WINNIE_MESSAGING_BRIDGE_SECRET", "synthetic-secret")
    delivery = {"id": "d1", "claim_token": "t1", "transport": "photon", "recipient": "x", "text": "Reply done WIN-1"}
    monkeypatch.setattr(reminders, "next_reminder", lambda *args, **kwargs: {"enabled": True, "delivery": delivery})
    monkeypatch.setattr(reminders, "reword", lambda text, settings: "Friendly: " + text)
    monkeypatch.setitem(app.dependency_overrides, reminders.get_reminder_store, lambda: object())
    with TestClient(app) as client:
        result = client.post("/api/internal/reminders/next", json={}, headers={"X-Winnie-Bridge-Secret": "synthetic-secret"})
    assert result.json()["delivery"]["text"] == "Friendly: Reply done WIN-1"
    assert result.json()["delivery"]["id"] == "d1"


def test_no_names_or_contacts_are_added_to_what_the_model_sees():
    generate = model(GOOD)
    reword(TEMPLATE, config(), generate=generate)
    assert "@" not in generate.calls[0] and "+1" not in generate.calls[0]
    assert TEMPLATE in generate.calls[0]
