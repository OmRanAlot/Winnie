"""Regression coverage for single-shot drafts rejected by their added purchase policy."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.tasks import authorize_tasks
from app.schemas.planning import DraftContents, ProposedTask
from app.services.planning_policies import apply_task_policies, schedule_order_policies


def task(id, **kwargs):
    return ProposedTask(id=id, title=id, rationale="Inferred proposal.", **kwargs)


def test_added_purchase_task_returns_a_valid_draft(monkeypatch, tmp_path):
    monkeypatch.setenv("WINNIE_PLANNING_MODE", "deepagents")
    monkeypatch.setenv("WINNIE_PLANNING_MODEL", "fake")
    monkeypatch.setenv("WINNIE_PLANNING_KNOWLEDGE_PATH", str(tmp_path / "missing.json"))

    async def plan(*args):
        return DraftContents(tasks=[ProposedTask(
            id="supplies", title="Finalize goodie bag supplies", rationale="Inferred giveaway.",
        )])

    monkeypatch.setattr("app.services.planning.deep_plan", plan)
    app.dependency_overrides[authorize_tasks] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post("/api/planning/drafts", json={
                "event_name": "Social", "idea": "Crafts and goodie bags",
                "event_type": "WiCS", "event_date": "2027-04-20",
            })
    finally:
        app.dependency_overrides.pop(authorize_tasks, None)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"persisted": False, "activated": False}
    tasks = {t["kind"]: t for t in body["data"]["tasks"]}
    assert tasks["order_items"]["due_date"] == "2027-03-30"
    assert tasks["order_items"]["suggested_role"] == "Treasurer"
    assert tasks["materials_list"]["due_date"] == "2027-03-29"
    assert tasks["materials_list"]["id"] in tasks["order_items"]["dependency_ids"]
    assert tasks["general"]["due_date"] is None


def test_purchase_cutoff_moves_prerequisites_and_preserves_earlier_dates():
    original = DraftContents(tasks=[
        task("scope", due_date=date(2027, 4, 1)),
        task("list", kind="materials_list", due_date=date(2027, 4, 10), dependency_ids=["scope"]),
        task("budget", kind="budget_approval", due_date=date(2027, 3, 1)),
        task("order", kind="order_items", due_date=date(2027, 4, 15)),
        task("unrelated"),
    ])
    fixed = schedule_order_policies(apply_task_policies(original), date(2027, 4, 20))
    tasks = {t.id: t for t in fixed.tasks}
    assert tasks["order"].due_date == date(2027, 3, 30)
    assert tasks["list"].due_date == date(2027, 3, 29)
    assert tasks["scope"].due_date == date(2027, 3, 29)
    assert tasks["budget"].due_date == date(2027, 3, 1)
    assert set(tasks["order"].dependency_ids) == {"list", "budget"}
    assert tasks["unrelated"].due_date is None
    assert original.tasks[3].due_date == date(2027, 4, 15)


def test_policy_edges_cannot_introduce_a_cycle():
    plan = DraftContents(tasks=[
        task("list", kind="materials_list", dependency_ids=["order"]),
        task("order", kind="order_items"),
    ])
    with pytest.raises(ValueError, match="cycle"):
        schedule_order_policies(plan, date(2027, 4, 20))


def test_purchase_prerequisite_cannot_be_moved_from_event_day():
    plan = DraftContents(tasks=[
        task("list", kind="materials_list", phase="during"),
        task("order", kind="order_items"),
    ])
    with pytest.raises(ValueError, match="preparation"):
        schedule_order_policies(plan, date(2027, 4, 20))
