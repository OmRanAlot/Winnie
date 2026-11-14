"""Pipeline integration tests use synthetic calendars, owners and deterministic stage outputs."""

import asyncio
import json
from datetime import date

import pytest

from app.pipeline_schemas import (
    Classification,
    ClassifiedHistory,
    Dependencies,
    PipelineRequest,
    Schedule,
)
from app.planning_schemas import DraftContents
from app.services.planning import PlanningUnavailable
from app.services.planning_history import enrich_history, read_taxonomy, timing_statistics
from app.services.planning_pipeline import apply_dependencies, run_pipeline


@pytest.fixture
def sources(tmp_path):
    taxonomy = read_taxonomy("Event,Category,Date\nWiCS Gala,Professional Development,4/26\n"
                             "Company workshop,Company Events,\n")
    history = {"schema_version": 1, "events": [{
        "calendar_row": 2, "name": "Old Company Workshop", "event_type": "Company",
        "start_date": "2026-10-20", "tasks": [
            {"title": "List materials", "historical_deadline": "10/6/2026",
             "historical_assignee_text": "coordinator@example.test", "evidence_id": "old-1"},
            {"title": "Purchase materials", "historical_deadline": "10/13/2026",
             "historical_assignee_text": "treasurer@example.test", "evidence_id": "old-2"},
        ],
    }]}
    roster = {"rosters": [{"semester_code": "fall-2026", "verified_by": "Synthetic fixture",
                           "members": [
                               {"member_code": "EC1", "display_name": "Example Coordinator",
                                "roles": ["Event Coordinator"], "aliases": ["coordinator@example.test"]},
                               {"member_code": "TREAS", "display_name": "Example Treasurer",
                                "roles": ["Treasurer"], "aliases": ["treasurer@example.test"]},
                           ]}]}
    paths = {}
    for name, data in (("taxonomy_path", taxonomy), ("knowledge_path", history), ("roster_path", roster)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(data), encoding="utf-8")
    return paths


def request():
    return PipelineRequest(event_name="New Company Workshop", idea="Hands-on workshop with materials",
                           event_date="2027-04-20", semester_code="fall-2026")


class FakeRunner:
    def __init__(self, invalid=None):
        self.calls = []
        self.payloads = {}
        self.invalid = invalid

    async def run(self, stage, schema, payload):
        self.calls.append(stage)
        self.payloads[stage] = payload
        category = {"category": "Company Events", "confidence": .9,
                    "rationale": "Similar reference event",
                    "taxonomy_evidence_ids": ["spring-calendar-row-3"]}
        tasks = [{"id": "list", "title": "List materials", "suggested_role": "Event Coordinator",
                  "evidence_ids": ["old-1"], "rationale": "Based on historical role mapping"},
                 {"id": "buy", "title": "Purchase materials", "suggested_role": "Treasurer",
                  "evidence_ids": ["old-2"], "rationale": "Based on historical role mapping"}]
        result = {
            "classify": category,
            "classify_history": {"events": [dict(event_id="calendar-row-2", **category)]},
            "tasks": {"tasks": tasks},
            "dependencies": {"edges": [{"upstream_task_id": "list", "downstream_task_id": "buy",
                                          "minimum_gap_days": 2, "rationale": "Purchasing needs the list"}]},
            "timeline": {"items": [
                {"task_id": "list", "due_date": "2027-03-28", "rationale": "Prerequisite ready before ordering",
                 "evidence_ids": ["old-1"]},
                {"task_id": "buy", "due_date": "2027-03-30", "rationale": "21-day ordering policy overrides history",
                 "evidence_ids": ["old-2"]},
            ]},
        }[stage]
        if self.invalid == "missing_history" and stage == "classify_history":
            result["events"] = []
        if self.invalid == "fake_taxonomy" and stage == "classify":
            result["taxonomy_evidence_ids"] = ["fake"]
        if self.invalid == "cycle" and stage == "dependencies":
            result["edges"].append({"upstream_task_id": "buy", "downstream_task_id": "list",
                                     "rationale": "Bad cycle"})
        if self.invalid == "too_short" and stage == "timeline":
            result["items"][1]["due_date"] = "2027-03-29"
        if self.invalid == "missing_schedule" and stage == "timeline":
            result["items"].pop()
        if self.invalid == "fake_evidence" and stage == "tasks":
            result["tasks"][0]["evidence_ids"] = ["fake"]
        return schema.model_validate(result)


@pytest.mark.asyncio
async def test_all_stages_historical_roles_buffers_and_handoffs(sources):
    runner = FakeRunner()
    draft = await run_pipeline(request(), **sources, mode="deepagents", runner=runner)
    assert runner.calls == ["classify", "classify_history", "tasks", "dependencies", "timeline"]
    assert len(draft.completed_stages) == 7
    assert draft.assignments[0].proposed_member_code == "EC1"
    assert draft.assignments[1].proposed_member_code == "TREAS"
    assert draft.plan.tasks[1].dependency_ids == ["list"]
    assert draft.plan.tasks[1].due_date == date(2027, 3, 30)
    assert len(draft.handoffs) == 1
    assert draft.timing_statistics[0]["median_lead_days"] == 14
    assert draft.historical_examples[0]["tasks"][0]["historical_roles"] == ["Event Coordinator"]
    assert "coordinator@example.test" not in draft.model_dump_json()
    assert draft.status == "draft"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing_history", "fake_taxonomy", "cycle", "too_short",
                                     "missing_schedule", "fake_evidence"])
async def test_invalid_stage_outputs_fail_before_assignment(sources, invalid):
    with pytest.raises(PlanningUnavailable):
        await run_pipeline(request(), **sources, mode="deepagents", runner=FakeRunner(invalid))


@pytest.mark.asyncio
async def test_missing_roster_leaves_person_and_historical_roles_unknown(sources):
    sources["roster_path"] = None
    draft = await run_pipeline(request(), **sources, mode="deepagents", runner=FakeRunner())
    assert all(a.proposed_member_code is None for a in draft.assignments)
    assert all(not t["historical_roles"] for t in draft.historical_examples[0]["tasks"])


@pytest.mark.asyncio
async def test_two_role_holders_require_resolution(sources):
    data = json.loads(sources["roster_path"].read_text())
    data["rosters"][0]["members"].append({"member_code": "EC2", "display_name": "Other Coordinator",
                                         "roles": ["Event Coordinator"]})
    sources["roster_path"].write_text(json.dumps(data))
    draft = await run_pipeline(request(), **sources, mode="deepagents", runner=FakeRunner())
    assert draft.assignments[0].candidate_member_codes == ["EC1", "EC2"]
    assert draft.assignments[0].proposed_member_code is None


def test_taxonomy_keeps_labels_and_undated_examples():
    taxonomy = read_taxonomy("Event,Category,Date\nGala,Professional Development,4/26\n"
                             "Undated workshop,Technical Workshop,\n")
    assert taxonomy["examples"][0]["category"] == "Professional Development"
    assert len(taxonomy["examples"]) == 2


def test_post_event_deadline_is_negative_lead_time_not_negative_effort():
    events = enrich_history({"events": [{"calendar_row": 2, "start_date": "2026-10-20", "tasks": [
        {"title": "Recap", "historical_deadline": "10/22/2026", "evidence_id": "recap"},
    ]}]}, [], "fall-2026")
    assert timing_statistics(events)[0]["median_lead_days"] == -2


def test_phase_order_rejected_without_dates():
    plan = DraftContents(tasks=[{"id": "after", "title": "After", "phase": "after", "rationale": "X"},
                                {"id": "before", "title": "Before", "rationale": "X"}])
    edges = Dependencies(edges=[{"upstream_task_id": "after", "downstream_task_id": "before",
                                 "rationale": "Invalid"}])
    with pytest.raises(ValueError, match="phases"):
        apply_dependencies(plan, edges, set())


@pytest.mark.asyncio
async def test_offline_pipeline_does_not_pretend_to_infer(sources):
    draft = await run_pipeline(request(), **sources)
    assert draft.classification.category == "Unknown"
    assert draft.dependencies.edges == []
    assert any("MOCK" in warning for warning in draft.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,schema", [
    ("classify", Classification), ("classify_history", ClassifiedHistory),
    ("tasks", DraftContents), ("dependencies", Dependencies), ("timeline", Schedule),
])
async def test_each_specialist_schema_through_real_harness(stage, schema):
    pytest.importorskip("deepagents")
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    from app.agents.stages import DeepStageRunner

    class StructuredFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    expected = await FakeRunner().run(stage, schema, {})
    model = StructuredFake(responses=[AIMessage(content="", tool_calls=[{
        "name": schema.__name__, "id": "synthetic-call", "type": "tool_call",
        "args": expected.model_dump(mode="json"),
    }])])
    result = await DeepStageRunner(model).run(stage, schema, {})
    assert result == expected


@pytest.mark.asyncio
async def test_full_pipeline_timeout(sources):
    class StalledRunner:
        async def run(self, *args):
            await asyncio.Event().wait()

    with pytest.raises(PlanningUnavailable):
        await run_pipeline(request(), **sources, mode="deepagents", runner=StalledRunner(),
                           timeout=.01)


@pytest.mark.asyncio
async def test_schedule_coverage_failure_is_repaired_with_specific_feedback(sources):
    class RepairRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.timeline_calls = 0

        async def run(self, stage, schema, payload):
            result = await super().run(stage, schema, payload)
            if stage == "timeline":
                self.timeline_calls += 1
                if self.timeline_calls == 1:
                    return result.model_copy(update={"items": result.items[:1]})
                assert "buy" in payload["validation_feedback"]
                assert payload["required_task_ids"] == ["list", "buy"]
                assert len(payload["previous_attempt"]["items"]) == 1
            return result

    runner = RepairRunner()
    draft = await run_pipeline(request(), **sources, mode="deepagents", runner=runner)
    assert runner.timeline_calls == 2
    assert runner.calls.count("tasks") == 1
    assert len(draft.schedule.items) == 2


def test_pipeline_api_offline_contract(sources, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes.tasks import authorize_tasks

    monkeypatch.setenv("WINNIE_PLANNING_MODE", "mock")
    monkeypatch.setenv("WINNIE_PLANNING_KNOWLEDGE_PATH", str(sources["knowledge_path"]))
    monkeypatch.setenv("WINNIE_PLANNING_TAXONOMY_PATH", str(sources["taxonomy_path"]))
    app.dependency_overrides[authorize_tasks] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post("/api/planning/pipeline-drafts", json=request().model_dump(mode="json"))
            assert response.status_code == 200
            assert len(response.json()["data"]["completed_stages"]) == 7
            assert response.json()["meta"] == {"persisted": False, "activated": False}
    finally:
        app.dependency_overrides.pop(authorize_tasks, None)
