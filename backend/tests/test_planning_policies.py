"""User role/deadline policies override precedents and model suggestions."""

import json
from datetime import date

import pytest

from app.schemas.pipeline import Dependencies, Schedule, ScheduleItem
from app.schemas.planning import DraftContents, ProposedTask
from app.services.planning_history import match_roles
from app.services.planning_pipeline import apply_schedule
from app.services.planning_policies import (
    apply_task_policies,
    demo_secretary_roster,
    required_order_edges,
    validate_order_deadlines,
    validate_policy_dependencies,
)


def task(id, title, **kwargs):
    return ProposedTask(id=id, title=title, rationale="Historical suggestion", **kwargs)


def test_highlander_hub_is_secretary_despite_wrong_model_role():
    plan = apply_task_policies(DraftContents(tasks=[
        task("hub", "Create and publish Highlander Hub event listing", suggested_role="Event Coordinator"),
    ]))
    assert plan.tasks[0].suggested_role == "Secretary"
    assert plan.tasks[0].kind == "highlander_hub"


def test_demo_secretary_resolves_to_anne_with_no_phone_or_email_output(tmp_path):
    path = tmp_path / "demo.json"
    path.write_text(json.dumps({"Secretary": {"name": "Anne Example", "email": "unused@example.test"}}))
    roster = demo_secretary_roster(path, "spring-2027")
    hub = apply_task_policies(DraftContents(tasks=[task("hub", "HighlanderHub event posting")]))
    assignments = match_roles(hub.tasks, [roster], "spring-2027")
    assert assignments[0]["proposed_member_name"] == "Anne Example"
    assert "unused@example.test" not in json.dumps(assignments)


@pytest.mark.parametrize("title", ["Purchase workshop materials", "Place food orders", "Order event supplies"])
def test_all_ordering_tasks_are_treasurer_with_fixed_cutoff(title):
    plan = apply_task_policies(DraftContents(tasks=[task("order", title, suggested_role="Event Coordinator")]))
    assert plan.tasks[0].suggested_role == "Treasurer"
    assert plan.tasks[0].kind == "order_items"
    plan.tasks[0].due_date = date(2027, 2, 10)
    validate_order_deadlines(plan, date(2027, 3, 3))
    plan.tasks[0].due_date = date(2027, 2, 11)
    with pytest.raises(ValueError, match="2027-02-10"):
        validate_order_deadlines(plan, date(2027, 3, 3))


def test_missing_ordering_task_is_added_without_turning_packing_into_ordering():
    plan = apply_task_policies(DraftContents(tasks=[task("pack", "Finalize goodie bag supplies and thank-you cards")]))
    assert plan.tasks[0].kind == "general"
    assert plan.tasks[1].kind == "order_items"
    assert plan.tasks[1].suggested_role == "Treasurer"


def test_budget_and_materials_must_precede_orders():
    plan = apply_task_policies(DraftContents(tasks=[task("list", "Prepare materials list"),
                                                   task("budget", "Confirm event budget"),
                                                   task("order", "Order supplies")]))
    assert set(required_order_edges(plan)) == {("list", "order"), ("budget", "order")}
    with pytest.raises(ValueError, match="Ordering policy"):
        validate_policy_dependencies(plan, Dependencies())


def test_schedule_rejects_late_order_even_when_historical_buffer_was_short():
    plan = apply_task_policies(DraftContents(tasks=[task("order", "Purchase event supplies")]))
    schedule = Schedule(items=[ScheduleItem(task_id=t.id, due_date="2027-02-20" if t.id == "order" else "2027-02-01", rationale="Old precedent") for t in plan.tasks])
    class Request:
        event_date = date(2027, 3, 3)
    with pytest.raises(ValueError, match="21 days"):
        apply_schedule(plan, schedule, Dependencies(), Request(), [])


def test_unknown_ordering_date_cannot_bypass_fixed_cutoff():
    plan = apply_task_policies(DraftContents(tasks=[task("order", "Order supplies")]))
    with pytest.raises(ValueError, match="21 days"):
        validate_order_deadlines(plan, date(2027, 3, 3))


@pytest.mark.parametrize("title", ["Receive ordered materials", "Assemble goodie bags with purchased supplies"])
def test_receiving_and_packing_are_not_ordering(title):
    plan = apply_task_policies(DraftContents(tasks=[task("receive", title)]))
    assert plan.tasks[0].kind == "general"


def test_revision_moves_prerequisites_earlier_and_preserves_dependency_gap():
    from app.schemas.pipeline import PipelineDraft
    from app.services.planning_revision import revise_policy_draft

    draft = PipelineDraft.model_validate({
        "mode": "deepagents", "request": {"event_name": "Example", "idea": "Example workshop",
          "event_date": "2027-03-03", "semester_code": "spring-2027"},
        "classification": {"category": "Technical Workshop", "confidence": 1, "rationale": "Example"},
        "historical_classifications": [], "historical_examples": [],
        "plan": {"tasks": [
            {"id": "list", "title": "Prepare materials list", "due_date": "2027-02-20", "rationale": "Old date"},
            {"id": "order", "title": "Order supplies", "due_date": "2027-02-25", "dependency_ids": ["list"], "rationale": "Old date"},
        ]}, "dependencies": {"edges": [{"upstream_task_id": "list", "downstream_task_id": "order",
                                        "minimum_gap_days": 2, "rationale": "Preparation time"}]},
        "schedule": {"items": [
            {"task_id": "list", "due_date": "2027-02-20", "rationale": "Old date"},
            {"task_id": "order", "due_date": "2027-02-25", "rationale": "Old date"},
        ]}, "assignments": [], "handoffs": [], "timing_statistics": [], "warnings": [], "completed_stages": [],
    })
    revised = revise_policy_draft(draft, [])
    dates = {task.id: task.due_date for task in revised.plan.tasks}
    assert dates == {"list": date(2027, 2, 8), "order": date(2027, 2, 10)}
    assert draft.plan.tasks[1].due_date == date(2027, 2, 25)
