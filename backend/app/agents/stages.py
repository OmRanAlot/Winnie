"""Staged-pipeline specialists: one separate, mandatory structured agent call per stage.

services/planning_pipeline.py asks a StageRunner for each stage in turn
(classify -> classify_history -> tasks -> dependencies -> timeline) and validates every
answer before the next stage sees it. DeepStageRunner is the real implementation, backed by
Deep Agents; tests pass a fake StageRunner, which is why the pipeline depends on the Protocol
and not on this class. Prompts live in agents/prompts.py, the agent call in agents/runner.py.
"""

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.agents.prompts import stage_prompt
from app.agents.runner import run_structured_agent


@runtime_checkable
class StageRunner(Protocol):
    """Anything that can answer one pipeline stage with a validated schema instance."""

    async def run[SchemaT: BaseModel](
        self, stage: str, schema: type[SchemaT], payload: Mapping[str, Any],
    ) -> SchemaT: ...


class DeepStageRunner:
    """Runs each stage as its own Deep Agents call, with that stage's prompt and schema."""

    def __init__(self, model):
        """`model` is a "provider:model" string or a LangChain chat model instance."""
        self.model = model

    async def run[SchemaT: BaseModel](
        self, stage: str, schema: type[SchemaT], payload: Mapping[str, Any],
    ) -> SchemaT:
        """Raises ValueError for an unknown stage before any model is contacted."""
        prompt = stage_prompt(stage)
        return await run_structured_agent(
            label=stage, model=self.model, system_prompt=prompt, schema=schema, payload=payload,
        )
