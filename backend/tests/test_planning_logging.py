"""Planning services must leave a server-side trail without leaking prompts to logs or HTTP."""

import asyncio
import logging

import pytest

from app.services.planning import PlanningUnavailable, create_draft
from app.services.planning_pipeline import run_pipeline
from tests.test_planning import knowledge  # noqa: F401
from tests.test_planning import request as draft_request
from tests.test_planning_pipeline import FakeRunner, sources  # noqa: F401
from tests.test_planning_pipeline import request as pipeline_request

SECRET_TEXT = "PRIVATE-MODEL-PROMPT-OR-KEY"


@pytest.mark.asyncio
async def test_pipeline_logs_start_each_stage_and_finish(sources, caplog):  # noqa: F811
    with caplog.at_level(logging.INFO, logger="app.services.planning_pipeline"):
        await run_pipeline(pipeline_request(), **sources, mode="deepagents", runner=FakeRunner())
    messages = [r.getMessage() for r in caplog.records]
    assert any("pipeline start" in m and "deepagents" in m for m in messages)
    for stage in ("classify", "classify_history", "tasks", "dependencies", "timeline"):
        assert any(f"stage {stage} done" in m for m in messages), stage
    assert any("pipeline done" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_logs_the_failure_type_but_not_the_message(sources, caplog):  # noqa: F811
    class Broken:
        async def run(self, *args):
            raise RuntimeError(SECRET_TEXT)

    with (caplog.at_level(logging.INFO, logger="app.services.planning_pipeline"),
          pytest.raises(PlanningUnavailable)):
        await run_pipeline(pipeline_request(), **sources, mode="deepagents", runner=Broken())
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "RuntimeError" in errors[0].getMessage()
    assert SECRET_TEXT not in caplog.text


@pytest.mark.asyncio
async def test_pipeline_logs_a_timeout(sources, caplog):  # noqa: F811
    class Stalled:
        async def run(self, *args):
            await asyncio.Event().wait()

    with (caplog.at_level(logging.INFO, logger="app.services.planning_pipeline"),
          pytest.raises(PlanningUnavailable)):
        await run_pipeline(pipeline_request(), **sources, mode="deepagents",
                           runner=Stalled(), timeout=0.01)
    assert any("timed out" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_provider_timeout_error_is_not_reported_as_our_pipeline_timeout(
        sources, caplog):  # noqa: F811
    class ProviderTimeout:
        async def run(self, *args):
            raise TimeoutError(SECRET_TEXT)

    with (caplog.at_level(logging.INFO, logger="app.services.planning_pipeline"),
          pytest.raises(PlanningUnavailable)):
        await run_pipeline(pipeline_request(), **sources, mode="deepagents",
                           runner=ProviderTimeout(), timeout=60)
    assert not any("timed out" in r.getMessage() for r in caplog.records)
    assert any("failed" in r.getMessage() and "TimeoutError" in r.getMessage()
               for r in caplog.records)
    assert SECRET_TEXT not in caplog.text


@pytest.mark.asyncio
async def test_single_shot_draft_timeout_is_labelled_as_a_timeout(knowledge, monkeypatch,  # noqa: F811
                                                                  caplog):
    async def stalled(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.services.planning.deep_plan", stalled)
    with (caplog.at_level(logging.INFO, logger="app.services.planning"),
          pytest.raises(PlanningUnavailable)):
        await create_draft(draft_request(), knowledge_path=knowledge, mode="deepagents",
                           model="fake", timeout=0.01)
    assert any("draft failed (timeout)" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_single_shot_draft_logs_mode_and_task_count(knowledge, caplog):  # noqa: F811
    with caplog.at_level(logging.INFO, logger="app.services.planning"):
        await create_draft(draft_request(), knowledge_path=knowledge, mode="mock")
    assert any("draft done" in r.getMessage() and "mock" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_single_shot_draft_failure_logs_type_only(knowledge, monkeypatch, caplog):  # noqa: F811
    async def broken(*args):
        raise RuntimeError(SECRET_TEXT)

    monkeypatch.setattr("app.services.planning.deep_plan", broken)
    with (caplog.at_level(logging.INFO, logger="app.services.planning"),
          pytest.raises(PlanningUnavailable)):
        await create_draft(draft_request(), knowledge_path=knowledge,
                           mode="deepagents", model="fake")
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "RuntimeError" in errors[0].getMessage()
    assert SECRET_TEXT not in caplog.text
