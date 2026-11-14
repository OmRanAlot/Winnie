"""Single-shot planner behind POST /api/planning/drafts: an offline mock and a Deep Agents run.

mock_plan: deterministic, no LLM. It echoes the historical checklist, so the endpoint works with
    no keys. It is explicitly NOT idea reasoning, and the service labels its drafts MOCK.
deep_plan: one Deep Agents call (agents/runner.py) that returns the whole plan as DraftContents.

The staged pipeline (agents/stages.py) is the richer alternative. Both only PROPOSE: neither has
any tool that can store tasks or send messages. services/planning.py validates what comes back.
"""

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
    """Ask one Deep Agents call for a full draft. `model` is a "provider:model" string."""
    return await run_structured_agent(
        label="plan", model=model, system_prompt=PLANNER_SYSTEM_PROMPT, schema=DraftContents,
        payload={"request": request.model_dump(mode="json"), "historical_examples": examples},
    )
