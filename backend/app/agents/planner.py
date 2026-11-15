"""Single-shot planner behind POST /api/planning/drafts: offline mock and structured model call.

mock_plan: deterministic, no LLM. It echoes the historical checklist, so the endpoint works with
    no keys. It is explicitly NOT idea reasoning, and the service labels its drafts MOCK.
deep_plan: one Gemini structured call, or the Deep Agents runner for other providers,
    returning the whole plan as DraftContents.

The staged pipeline (agents/stages.py) is the richer alternative. Both only PROPOSE: neither has
any tool that can store tasks or send messages. services/planning.py validates what comes back.
"""

import json

from app.agents.models import GEMINI_PREFIX, planning_model
from app.agents.prompts import PLANNER_SYSTEM_PROMPT
from app.agents.runner import run_structured_agent
from app.schemas.planning import DraftContents, PlanningRequest, ProposedTask


def mock_plan(request: PlanningRequest, examples: list[dict]) -> DraftContents:
    """Deterministic historical checklist, explicitly not idea reasoning by an LLM."""
    tasks, seen = [], set()
    for example in examples:
        for historical in example["tasks"]:
            key = historical["title"].casefold()
            if key in seen:
                continue
            seen.add(key)
            tasks.append(ProposedTask(
                id=f"draft-{len(tasks) + 1}", title=historical["title"],
                phase="after" if any(word in key for word in ("recap", "reflection")) else "before",
                evidence_ids=[historical["evidence_id"]],
                rationale="Historical checklist example; confirm relevance to the new idea.",
            ))
    if not tasks:
        tasks.append(ProposedTask(
            id="draft-1", title="Confirm event scope and requirements",
            rationale="No matching task history; requirements must be gathered before planning.",
        ))
    return DraftContents(tasks=tasks, questions=[
        "What budget, audience, venue and materials does this idea require?",
        "Which role holders can take ownership, and what lead times are feasible?",
    ])


async def deep_plan(request: PlanningRequest, examples: list[dict], model: str) -> DraftContents:
    """Use one Gemini structured call, or the agent harness for other providers."""
    if isinstance(model, str) and model.startswith(GEMINI_PREFIX):
        # This endpoint needs one answer, not filesystem tools or an agent loop.
        # Force the answer schema as the only tool, without agent-loop round trips.
        structured = planning_model(model).with_structured_output(
            DraftContents, method="function_calling",
        )
        result = await structured.ainvoke([
            ("system", PLANNER_SYSTEM_PROMPT),
            ("human", json.dumps({
                "request": request.model_dump(mode="json"), "historical_examples": examples,
            })),
        ])
        return DraftContents.model_validate(result)
    return await run_structured_agent(
        label="plan", model=model, system_prompt=PLANNER_SYSTEM_PROMPT, schema=DraftContents,
        payload={"request": request.model_dump(mode="json"), "historical_examples": examples},
    )
