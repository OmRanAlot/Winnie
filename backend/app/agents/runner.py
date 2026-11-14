"""The one place that builds and invokes a LangChain Deep Agents agent.

Both the single-shot planner (agents/planner.py) and the staged pipeline (agents/stages.py)
need the same thing: a tool-free agent that answers with a Pydantic schema. run_structured_agent
does that once, and adds the logging and safety defaults, so neither caller repeats it.

Safety defaults, deliberately not configurable:
* tools=[] and StateBackend(): the agent gets only a virtual in-memory filesystem. It has no
  host files, shell, database or messaging, so a prompt-injected agent cannot do anything.
* A recursion limit bounds the agent loop.
* At INFO and above, logs carry the label, model name, timing and exception TYPE only.
  Payloads and prompts are never logged, and exception messages appear only in the DEBUG
  traceback, because provider errors can echo prompts or keys. Do not run DEBUG in production.

deepagents is imported inside the function so offline development (mock mode) and the test
suite work without provider packages or credentials.
"""

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.agents.models import describe_model, planning_model

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 40  # max LangGraph steps per agent run (the harness default is far higher)


async def run_structured_agent[SchemaT: BaseModel](
    *,
    label: str,
    model: Any,
    system_prompt: str,
    schema: type[SchemaT],
    payload: Mapping[str, Any],
) -> SchemaT:
    """Run one Deep Agents call and return its answer validated as `schema`.

    label: short name for the logs, e.g. a stage name or "plan".
    model: a "provider:model" string or a LangChain chat model instance. google_genai: strings
        are configured explicitly in agents/models.py.
    payload: JSON-serialisable context sent as the single user message (dates are stringified).
    Raises whatever the provider or harness raises, or pydantic.ValidationError when the
    structured answer does not match `schema`. Callers decide how to present failures.
    """
    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend

    model_name = describe_model(model)
    logger.info("agent[%s] start model=%s schema=%s", label, model_name, schema.__name__)
    started = time.perf_counter()
    try:
        agent = create_deep_agent(
            model=planning_model(model), tools=[], system_prompt=system_prompt,
            response_format=schema, backend=StateBackend(),
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": json.dumps(payload, default=str)}]},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        validated = schema.model_validate(result["structured_response"])
    except asyncio.CancelledError:
        logger.warning("agent[%s] cancelled after %.0f ms (timeout or shutdown)",
                       label, _elapsed_ms(started))
        raise
    except Exception as exc:
        logger.error("agent[%s] failed after %.0f ms: %s",
                     label, _elapsed_ms(started), type(exc).__name__)
        logger.debug("agent[%s] failure detail", label, exc_info=True)
        raise
    logger.info("agent[%s] ok in %.0f ms", label, _elapsed_ms(started))
    return validated


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
