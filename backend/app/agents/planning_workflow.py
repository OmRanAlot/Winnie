"""Checkpointed LangGraph envelope around the existing Deep Agents specialists."""

import hashlib
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.schemas.planning_runs import PlanningReview


def draft_revision(draft: dict) -> str:
    return hashlib.sha256(json.dumps(draft, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PlanningState(TypedDict, total=False):
    request: dict
    draft: dict
    decision: dict


def build_planning_workflow(checkpointer, generate):
    async def generate_node(state: PlanningState):
        return {"draft": await generate(state["request"])}

    def review_node(state: PlanningState):
        revision = draft_revision(state["draft"])
        answer = interrupt({
            "kind": "event_plan_review", "revision": revision,
            "task_count": len(state["draft"]["plan"]["tasks"]), "activated": False,
        })
        review = PlanningReview.model_validate(answer)
        if review.expected_revision != revision:
            raise ValueError("Review does not match the checkpointed draft.")
        return {"decision": review.model_dump(mode="json")}

    graph = StateGraph(PlanningState)
    graph.add_node("generate", generate_node)
    graph.add_node("review", review_node)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "review")
    graph.add_edge("review", END)
    return graph.compile(checkpointer=checkpointer)
