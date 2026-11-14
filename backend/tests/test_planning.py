"""Planning safety and historical retrieval tests; source data is synthetic."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.routes.tasks import authorize_tasks
from app.schemas.planning import DraftContents, PlanningRequest
from app.services.planning import PlanningUnavailable, create_draft
from app.services.planning_context import build_knowledge, load_examples


@pytest.fixture
def knowledge(tmp_path):
    calendar = (
        "Date,Event,Event Type,Someone,Total\n"
        "9/2,Student Involvement Fair,Tabling,TRUE,1\n"
        "10/21,GBM 2,WiCS,FALSE,0\n"
        "11/11,WiCS Technical Workshop,WiCS,TRUE,1\n"
        "11/18,Verizon Info Session,Company,TRUE,1\n"
        "10/30,Partner Workshop,Club Collab,FALSE,0\n"
        "10/3 & 10/4,GirlHacks,WiCS,TRUE,1\n"
        "10/2,,,TRUE,1\n"
        ",TOTAL:,,,\n"
    )
    rows = [
        ["Title"], ["Event", "Task Name", "Deadline", "Winnie Task ID"],
        ["Involvement Fair", "Reserve table", "8/17/2026", "TEST-1"],
        ["GBM 2", "Create slides", "10/7/2026", "TEST-2"],
        ["WiCS Tech Workshop 1", "Review workshop materials", "11/5/2026", "TEST-3"],
        ["Verizon Event", "Confirm arrival instructions", "11/16/2026", "TEST-4"],
        ["Elections", "Prepare interviews", "10/28/2026", "TEST-5"],
    ]
    data = build_knowledge(calendar, rows, year=2026, spreadsheet_id="test-sheet",
                           tab_name="October 2026")
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def request(**kwargs):
    return PlanningRequest(event_name="Spring GBM", idea="A games and introductions meeting",
                           event_type="WiCS", event_date="2027-04-20", **kwargs)


def test_calendar_join_excludes_attendance_and_non_events(knowledge):
    data = json.loads(knowledge.read_text())
    assert len(data["events"]) == 6
    assert data["events"][0]["tasks"][0]["source_task_id"] == "TEST-1"
    assert data["events"][0]["tasks"][0]["source_range"] == "'October 2026'!A3:H3"
    assert data["unmatched_tracker_groups"] == ["Elections"]
    assert "TRUE" not in json.dumps(data)
    assert "Someone" not in json.dumps(data)
    assert data["events"][-1]["date_text"] == "10/3 & 10/4"


def test_wics_subtypes_do_not_mix_hackathon_gbm_workshop(knowledge):
    examples, _ = load_examples(knowledge, request())
    assert [event["name"] for event in examples] == ["GBM 2"]
    examples, warnings = load_examples(knowledge, request(event_format="hackathon"))
    assert examples == []
    assert any("No matching task history" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_offline_draft_has_provenance_and_no_invented_dates_or_owners(knowledge):
    draft = await create_draft(request(), knowledge_path=knowledge)
    assert draft.status == "draft"
    assert draft.mode == "mock"
    assert draft.tasks[0].evidence_ids == ["october-row-4"]
    assert all(task.due_date is None and task.suggested_role is None for task in draft.tasks)
    assert any("MOCK" in warning for warning in draft.warnings)


def task(id, dependencies=(), **kwargs):
    return dict(id=id, title=id, dependency_ids=list(dependencies), rationale="Proposed", **kwargs)


@pytest.mark.parametrize("tasks", [
    [task("a"), task("a")],
    [task("a", ["missing"])],
    [task("a", ["b"]), task("b", ["a"])],
    [task("a", ["a"])],
    [task("a", ["b"], due_date="2027-04-01"), task("b", due_date="2027-04-02")],
])
def test_invalid_dependency_graphs_rejected(tasks):
    with pytest.raises(ValidationError):
        DraftContents(tasks=tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_task", [
    task("a", evidence_ids=["fabricated"]),
    task("a", due_date="2027-04-21"),
    task("a", due_date="2027-04-19", phase="after"),
    task("a", due_date="2027-04-19", phase="during"),
])
async def test_model_output_revalidated(knowledge, monkeypatch, bad_task):
    async def fake_plan(*args):
        return DraftContents(tasks=[bad_task])
    monkeypatch.setattr("app.services.planning.deep_plan", fake_plan)
    with pytest.raises(PlanningUnavailable):
        await create_draft(request(), knowledge_path=knowledge, mode="deepagents", model="fake")


@pytest.mark.asyncio
async def test_model_timeout_and_errors_do_not_expose_prompt(knowledge, monkeypatch):
    async def broken(*args):
        raise RuntimeError("PRIVATE MODEL PROMPT OR KEY")
    monkeypatch.setattr("app.services.planning.deep_plan", broken)
    with pytest.raises(PlanningUnavailable, match="Model provider") as error:
        await create_draft(request(), knowledge_path=knowledge, mode="deepagents", model="fake")
    assert "PRIVATE" not in str(error.value)


def test_api_draft_and_missing_context(knowledge, monkeypatch):
    monkeypatch.setenv("WINNIE_PLANNING_KNOWLEDGE_PATH", str(knowledge))
    monkeypatch.setenv("WINNIE_PLANNING_MODE", "mock")
    app.dependency_overrides[authorize_tasks] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post("/api/planning/drafts", json=request().model_dump(mode="json"))
            assert response.status_code == 200
            assert response.json()["meta"] == {"persisted": False, "activated": False}
            monkeypatch.setenv("WINNIE_PLANNING_KNOWLEDGE_PATH", str(knowledge) + ".missing")
            assert client.post("/api/planning/drafts", json=request().model_dump(mode="json")).status_code == 503
    finally:
        app.dependency_overrides.pop(authorize_tasks, None)


def test_api_requires_configured_key(monkeypatch):
    monkeypatch.setenv("WINNIE_TASK_API_KEY", "synthetic-test-key")
    with TestClient(app) as client:
        assert client.post("/api/planning/drafts", json=request().model_dump(mode="json")).status_code == 401


@pytest.mark.asyncio
async def test_real_deepagents_graph_with_fake_model(knowledge):
    """Exercise the installed harness/structured response without a key or network call."""
    pytest.importorskip("deepagents")
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    from app.agents.planner import deep_plan

    class StructuredFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = StructuredFake(responses=[AIMessage(content="", tool_calls=[{
        "name": "DraftContents", "id": "fake-call", "type": "tool_call",
        "args": {"tasks": [task("a", evidence_ids=["october-row-4"])], "questions": []},
    }])])
    examples, _ = load_examples(knowledge, request())
    result = await deep_plan(request(), examples, model)
    assert result.tasks[0].evidence_ids == ["october-row-4"]
