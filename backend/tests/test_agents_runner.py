"""Shared Deep Agents runner tests. A fake harness replaces deepagents, so no model is called."""

import asyncio
import json
import logging
from datetime import date

import pytest
from pydantic import ValidationError

from app.agents.models import describe_model
from app.agents.runner import RECURSION_LIMIT, run_structured_agent
from app.schemas.pipeline import Classification

VALID = {
    "category": "Company Events", "confidence": 0.9, "rationale": "Similar reference event",
    "taxonomy_evidence_ids": ["spring-calendar-row-3"],
}
SECRET_TEXT = "PRIVATE-PAYLOAD-TEXT"


class FakeAgent:
    def __init__(self, result=None, error=None, stall=False):
        self.result, self.error, self.stall = result, error, stall
        self.invocations = []

    async def ainvoke(self, state, config=None):
        self.invocations.append((state, config))
        if self.stall:
            await asyncio.Event().wait()
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def harness(monkeypatch):
    """Patch deepagents.create_deep_agent and record how the agent was built."""
    built = {}

    def install(agent):
        def fake_create(**kwargs):
            built.update(kwargs)
            return agent

        monkeypatch.setattr("deepagents.create_deep_agent", fake_create)
        return built

    return install


async def run(**overrides):
    kwargs = {"label": "classify", "model": "openai:example", "system_prompt": "RULES",
              "schema": Classification, "payload": {"request": SECRET_TEXT}}
    return await run_structured_agent(**{**kwargs, **overrides})


@pytest.mark.asyncio
async def test_builds_a_tool_free_state_backed_agent(harness):
    built = harness(FakeAgent({"structured_response": VALID}))
    await run()
    assert built["tools"] == []
    assert built["system_prompt"] == "RULES"
    assert built["response_format"] is Classification
    assert built["model"] == "openai:example"
    assert type(built["backend"]).__name__ == "StateBackend"


@pytest.mark.asyncio
async def test_sends_payload_as_one_json_user_message_with_a_recursion_limit(harness):
    agent = FakeAgent({"structured_response": VALID})
    harness(agent)
    await run(payload={"when": date(2027, 4, 20)})
    state, config = agent.invocations[0]
    assert config == {"recursion_limit": RECURSION_LIMIT}
    (message,) = state["messages"]
    assert message["role"] == "user"
    assert json.loads(message["content"]) == {"when": "2027-04-20"}


@pytest.mark.asyncio
async def test_returns_the_validated_schema_instance(harness):
    harness(FakeAgent({"structured_response": VALID}))
    result = await run()
    assert isinstance(result, Classification)
    assert result.category == "Company Events"


@pytest.mark.asyncio
async def test_invalid_structured_response_raises_validation_error(harness):
    harness(FakeAgent({"structured_response": {"category": "Company Events"}}))
    with pytest.raises(ValidationError):
        await run()


@pytest.mark.asyncio
async def test_success_is_logged_with_label_and_model_but_not_the_payload(harness, caplog):
    harness(FakeAgent({"structured_response": VALID}))
    with caplog.at_level(logging.INFO, logger="app.agents.runner"):
        await run()
    text = caplog.text
    assert "classify" in text and "openai:example" in text and "ms" in text
    assert SECRET_TEXT not in text


@pytest.mark.asyncio
async def test_failure_is_logged_by_exception_type_only(harness, caplog):
    harness(FakeAgent(error=RuntimeError(f"provider echoed {SECRET_TEXT}")))
    with caplog.at_level(logging.INFO, logger="app.agents.runner"), pytest.raises(RuntimeError):
        await run()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].getMessage()
    assert SECRET_TEXT not in caplog.text


@pytest.mark.asyncio
async def test_cancellation_is_logged_as_a_warning_and_propagates(harness, caplog):
    harness(FakeAgent(stall=True))
    with caplog.at_level(logging.INFO, logger="app.agents.runner"), pytest.raises(TimeoutError):
        await asyncio.wait_for(run(), 0.01)
    assert any(r.levelno == logging.WARNING and "cancelled" in r.getMessage()
               for r in caplog.records)


def test_describe_model_shows_strings_and_class_names_only():
    assert describe_model("google_genai:gemini-x") == "google_genai:gemini-x"

    class ChatThing:
        api_key = "should-never-appear"

    assert describe_model(ChatThing()) == "ChatThing"
