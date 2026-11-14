"""DeepStageRunner tests: stage dispatch and the StageRunner contract, with no model calls."""

import inspect

import pytest

from app.agents import stages
from app.agents.prompts import STAGE_NAMES, stage_prompt
from app.agents.stages import DeepStageRunner, StageRunner
from app.schemas.pipeline import Classification


class RecordingRunner:
    """Stands in for run_structured_agent and records how the stage runner calls it."""

    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return "validated-result"


@pytest.fixture
def recorder(monkeypatch):
    recording = RecordingRunner()
    monkeypatch.setattr(stages, "run_structured_agent", recording)
    return recording


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGE_NAMES)
async def test_each_stage_runs_with_its_own_prompt_label_and_schema(recorder, stage):
    runner = DeepStageRunner("openai:example")
    result = await runner.run(stage, Classification, {"k": "v"})
    assert result == "validated-result"
    (call,) = recorder.calls
    assert call["label"] == stage
    assert call["system_prompt"] == stage_prompt(stage)
    assert call["schema"] is Classification
    assert call["payload"] == {"k": "v"}
    assert call["model"] == "openai:example"


@pytest.mark.asyncio
async def test_unknown_stage_fails_before_any_agent_is_built(recorder):
    with pytest.raises(ValueError, match="Unknown planning stage"):
        await DeepStageRunner("openai:example").run("nope", Classification, {})
    assert recorder.calls == []


def test_deep_stage_runner_has_an_async_run_like_the_stage_runner_protocol():
    # runtime_checkable only proves a `run` attribute exists, so also require it to be async.
    assert isinstance(DeepStageRunner("openai:example"), StageRunner)
    assert inspect.iscoroutinefunction(DeepStageRunner.run)
