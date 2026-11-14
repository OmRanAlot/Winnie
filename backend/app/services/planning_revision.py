"""Apply confirmed planning policies to an existing draft without another model run."""

from datetime import timedelta

from app.pipeline_schemas import Dependencies, PipelineDraft, Schedule, ScheduleItem
from app.services.planning_history import match_roles
from app.services.planning_pipeline import apply_dependencies, apply_schedule
from app.services.planning_policies import (
    ORDER_LEAD_DAYS,
    apply_task_policies,
    required_order_edges,
)


def revise_policy_draft(draft: PipelineDraft, rosters: list) -> PipelineDraft:
    plan = apply_task_policies(draft.plan)
    edges = [edge.model_copy(deep=True) for edge in draft.dependencies.edges]
    lookup = {(edge.upstream_task_id, edge.downstream_task_id): edge for edge in edges}
    for upstream, downstream in required_order_edges(plan):
        if (upstream, downstream) in lookup:
            lookup[upstream, downstream].minimum_gap_days = max(1, lookup[upstream, downstream].minimum_gap_days)
        else:
            from app.pipeline_schemas import Dependency

            edges.append(Dependency(upstream_task_id=upstream, downstream_task_id=downstream,
                                    minimum_gap_days=1,
                                    rationale="User policy: item requirements and budget approval must be ready before the Treasurer orders."))
    dependencies = Dependencies(edges=edges)
    evidence = {t["evidence_id"] for e in draft.historical_examples for t in e["tasks"]}
    plan = apply_dependencies(plan, dependencies, evidence)
    items = {item.task_id: item.model_copy(deep=True) for item in draft.schedule.items}
    for task in plan.tasks:
        items.setdefault(task.id, ScheduleItem(task_id=task.id, due_date=None,
                                               rationale="Added to satisfy user-confirmed planning policy."))
    cutoff = draft.request.event_date - timedelta(days=ORDER_LEAD_DAYS)
    for task in plan.tasks:
        if task.kind == "order_items":
            item = items[task.id]
            item.due_date = min(item.due_date, cutoff) if item.due_date else cutoff
            item.rationale = f"User-confirmed ordering cutoff: no later than {cutoff.isoformat()}, 21 days before the event."
            item.evidence_ids = []
    # Moving a prerequisite earlier can require its own predecessors to move too.
    for _ in range(len(plan.tasks)):
        changed = False
        for edge in edges:
            upstream, downstream = items[edge.upstream_task_id], items[edge.downstream_task_id]
            if downstream.due_date is None:
                continue
            latest = downstream.due_date - timedelta(days=edge.minimum_gap_days)
            if upstream.due_date is None or upstream.due_date > latest:
                upstream.due_date = latest
                upstream.rationale = "Moved earlier to preserve prerequisite timing after applying the user-confirmed 21-day ordering policy."
                upstream.evidence_ids = []
                changed = True
        if not changed:
            break
    schedule = Schedule(items=[items[t.id] for t in plan.tasks], warnings=draft.schedule.warnings)
    plan = apply_schedule(plan, schedule, dependencies, draft.request, draft.historical_examples)
    assignments = match_roles(plan.tasks, rosters, draft.request.semester_code)
    assigned = {item["task_id"]: item for item in assignments}
    handoffs = [{"upstream": assigned[edge.upstream_task_id],
                 "downstream": assigned[edge.downstream_task_id],
                 "minimum_gap_days": edge.minimum_gap_days, "rationale": edge.rationale}
                for edge in edges
                if assigned[edge.upstream_task_id]["role"] != assigned[edge.downstream_task_id]["role"]
                or assigned[edge.upstream_task_id]["proposed_member_code"] != assigned[edge.downstream_task_id]["proposed_member_code"]]
    return PipelineDraft.model_validate({**draft.model_dump(mode="json"),
        "plan": plan, "dependencies": dependencies, "schedule": schedule,
        "assignments": assignments, "handoffs": handoffs,
        "warnings": draft.warnings + [
            "User-confirmed policy revision: Secretary owns Highlander Hub; Treasurer orders all items at least 21 days before the event. Prerequisite dates were moved earlier where required.",
            "Secretary matching uses the current demo roster; this is not a verified future-semester appointment.",
        ], "completed_stages": draft.completed_stages + ["user_policy_revision"],
    })
