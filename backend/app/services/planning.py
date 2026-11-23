"""Coordinate read-only planning and validate model output before returning a draft.

create_draft backs POST /api/planning/drafts: it loads the historical examples, asks the mock or
Deep Agents planner (app/agents/planner.py) for a draft, then re-validates the output. Failures
become PlanningUnavailable with a generic message, because provider errors can contain prompts
or keys. The real cause is logged server-side by exception type only (never the message).
"""

import asyncio
import logging
import time
from datetime import date
from pathlib import Path

from app.agents.planner import deep_plan, mock_plan
from app.schemas.planning import PlanningDraft, PlanningRequest
from app.services.planning_context import load_examples
from app.services.planning_policies import (
    apply_task_policies,
    schedule_order_policies,
    validate_order_deadlines,
)

logger = logging.getLogger(__name__)


class PlanningUnavailable(Exception):
    """Configuration, knowledge or provider prevented a draft."""

    def __init__(self, message, public_message=None):
        super().__init__(message)
        self.public_message = public_message


def validate_draft(contents, request, examples):
    evidence = {task["evidence_id"] for example in examples for task in example["tasks"]}
    for task in contents.tasks:
        if set(task.evidence_ids) - evidence:
            raise ValueError("Planner cited evidence outside the retrieved examples.")
        if task.due_date:
            if task.phase == "before" and task.due_date > request.event_date:
                raise ValueError("Preparation task is due after the event.")
            if task.phase == "after" and task.due_date < request.event_date:
                raise ValueError("Follow-up task is due before the event.")
            if task.phase == "during" and task.due_date != request.event_date:
                raise ValueError("Event-day task must be due on the event date.")


async def create_draft(request: PlanningRequest, *, knowledge_path: Path,
                       mode: str = "mock", model: str = "", timeout: float = 60) -> PlanningDraft:
    logger.info("draft start mode=%s timeout=%.0fs", mode, timeout)
    started = time.perf_counter()
    stage = "context"
    try:
        try:
            examples, warnings = load_examples(knowledge_path, request)
        except FileNotFoundError:
            # Private history is not shipped with a fresh checkout. AI planning
            # can use the idea alone, but the offline historical checklist cannot.
            if mode != "deepagents":
                raise
            examples = []
            warnings = [
                ("Historical planning context is not available. This plan is based only on "
                 "your event idea; tasks, roles and dates are inferred and require review."),
            ]
            logger.warning("draft historical context missing; planning from the event idea only")
        logger.info("draft loaded %d historical example event(s)", len(examples))
        stage = "model"
        if mode == "mock":
            contents = mock_plan(request, examples)
            warnings.append("MOCK: historical checklist only; the idea has not been analyzed by an LLM.")
        elif mode == "deepagents" and model:
            contents = await asyncio.wait_for(deep_plan(request, examples, model), timeout)
        else:
            raise ValueError("Configure planning mode and explicit provider:model.")
        stage = "policies"
        contents = apply_task_policies(contents)
        contents = schedule_order_policies(contents, request.event_date)
        stage = "evidence_and_phase"
        validate_draft(contents, request, examples)
        stage = "ordering_deadlines"
        validate_order_deadlines(contents, request.event_date)
    except (OSError, ValueError, KeyError, ImportError, TimeoutError) as exc:
        category = ("timeout" if isinstance(exc, TimeoutError)
                    else "configuration, context or output")
        logger.error("draft failed (%s): %s stage=%s", category, type(exc).__name__, stage)
        logger.debug("draft failure detail", exc_info=True)
        public = None
        if isinstance(exc, ImportError):
            public = "The deployed backend is missing its planning provider package. Rebuild and deploy the updated backend image."
        elif isinstance(exc, FileNotFoundError):
            public = "Offline planning history is unavailable. Configure AI planning or restore the server's reviewed planning context."
        raise PlanningUnavailable("Planning configuration, context or output is invalid.", public) from exc
    except Exception as exc:
        # Provider errors may contain private prompts or credentials; never expose them in HTTP
        # or in logs above DEBUG.
        logger.error("draft failed (model provider): %s", type(exc).__name__)
        logger.debug("draft failure detail", exc_info=True)
        raise PlanningUnavailable("Model provider could not produce a draft.") from exc
    if request.event_date < date.today():
        warnings.append("Event date is in the past; this is a retrospective draft.")
    if any(task.due_date is None for task in contents.tasks):
        warnings.append("Some deadlines are unknown and must be set during review.")
    warnings.append("Draft only; not saved, restart-durable, approved or activated.")
    logger.info("draft done mode=%s tasks=%d warnings=%d in %.0f ms", mode, len(contents.tasks),
                len(warnings), (time.perf_counter() - started) * 1000)
    return PlanningDraft(**contents.model_dump(), mode=mode, request=request,
                         warnings=warnings, historical_examples=examples)
