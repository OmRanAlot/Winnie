"""Role-based skills and task candidate matching. Gemini is replaced by fakes: offline and free."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import members as route
from app.services import member_skills, task_matching
from app.services.member_skills import SkillProfile, grounded, with_skills
from app.services.task_matching import Judgement, rank, workload

ROLE = "Role: Treasurer\nOwns club money.\n- Draft and manage the annual budgets.\n- Process reimbursements."


def test_grounded_drops_skills_without_evidence_in_role_text():
    profile = SkillProfile.model_validate({
        "technical": [{"skill": "Budgeting", "evidence": "Draft and manage the annual budgets."},
                      {"skill": "Python", "evidence": "Writes Python scripts"},          # invented
                      {"skill": "budgeting", "evidence": "Process reimbursements."}],    # duplicate
        "soft": [{"skill": "Detail orientation", "evidence": "process  REIMBURSEMENTS"}],
    })
    assert grounded(profile, ROLE) == {
        "technical": [{"skill": "Budgeting", "evidence": "Draft and manage the annual budgets."}],
        "soft": [{"skill": "Detail orientation", "evidence": "process REIMBURSEMENTS"}],
    }


def test_supabase_skills_win_over_generated_file():
    skills = {"A": {"technical": [{"skill": "x", "evidence": "e"}], "soft": [], "source": "role-derived"}}
    a, b = with_skills([{"code": "A", "skills": []}, {"code": "B", "skills": ["manual"]}], skills)
    assert a["skills"] == ["x"] and a["skills_source"] == "role-derived"
    assert b["skills"] == ["manual"] and b["skills_source"] == "supabase"


def test_generate_all_calls_gemini_once_per_distinct_role(monkeypatch):
    calls = []

    async def fake_extract(member, settings):
        calls.append(member["board_role"])
        return {"technical": [{"skill": "design", "evidence": "x"}], "soft": []}

    monkeypatch.setattr(member_skills, "extract_skills", fake_extract)
    members = [{"code": c, "display_name": c, "board_role": "PR Chair", "role_description": "d"}
               for c in ("A", "B")]
    import asyncio
    out = asyncio.run(member_skills.generate_all(members, SimpleNamespace()))
    assert calls == ["PR Chair"] and set(out) == {"A", "B"} and out["B"]["source"] == "role-derived"


def test_addressed_to_detects_the_recipient_only():
    assert task_matching.addressed_to("Send purchase list to Sharanya", "Sharanya Raj")
    assert not task_matching.addressed_to("Sharanya to send purchase list", "Sharanya Raj")
    assert not task_matching.addressed_to("Talk to sponsors", "Sharanya Raj")


def test_workload_counts_open_and_due_this_week():
    tasks = [{"id": 1, "status": "todo", "due_date": "2026-11-16"},
             {"id": 2, "status": "in_progress", "due_date": "2026-12-30"},
             {"id": 3, "status": "done", "due_date": "2026-11-15"}]
    loads = workload(tasks, {"1": ["A"], "2": ["A", "B"], "3": ["B"]}, today=date(2026, 11, 14))
    assert loads == {"A": {"open": 2, "due_this_week": 1}, "B": {"open": 1, "due_this_week": 0}}


MEMBERS = {
    "A": {"display_name": "Ann", "board_role": "Treasurer", "skills": ["budgeting", "purchasing"]},
    "B": {"display_name": "Bea", "board_role": "Treasurer", "skills": ["budgeting"]},
    "C": {"display_name": "Cy", "board_role": "PR", "skills": ["graphic design"]},
}


def test_rank_filters_invented_codes_and_skills_then_orders_by_fit_and_load():
    judgements = [
        Judgement(code="A", fit="strong", reason="Handles money", matched_skills=["Budgeting"]),
        Judgement(code="B", fit="strong", reason="Handles money", matched_skills=["budgeting"]),
        Judgement(code="C", fit="possible", reason="?", matched_skills=["juggling"]),   # no real skill
        Judgement(code="Z", fit="strong", reason="ghost", matched_skills=["budgeting"]),  # not a member
        Judgement(code="A", fit="none", reason="dup", matched_skills=["budgeting"]),
    ]
    loads = {"A": {"open": 5, "due_this_week": 3}, "B": {"open": 1, "due_this_week": 0}}
    result = rank(judgements, MEMBERS, loads)
    assert [c["code"] for c in result] == ["B", "A"]
    assert result[1]["matched_skills"] == ["budgeting"] and result[1]["due_this_week"] == 3


class FakeTasks:
    def get(self, task_id):
        return {"id": str(task_id), "title": "Order snacks", "status": "todo", "updated_at": "t"}

    def list(self, *, semester_code=None, limit=50, offset=0, **_):
        rows = [{"id": "00000000-0000-0000-0000-000000000001", "assignee_text": "Ann",
                 "status": "todo", "due_date": None}]
        return rows[offset:offset + limit], 1


class FakeMembers:
    def aliases(self, semester):
        return [{"alias": "Ann", "member_code": "A"}]

    def list_active(self):
        return [{"code": c, **m, "role_description": "", "skills": m["skills"]} for c, m in MEMBERS.items()]

    def previous_roles(self):
        return {}


@pytest.fixture
def client(monkeypatch, signed_in_member):
    monkeypatch.setattr(route, "load_skills", dict)
    monkeypatch.setattr(route, "load_previous_roles", dict)
    # Independent of the developer's .env: a fixed key and semester.
    monkeypatch.setattr(route, "Settings", lambda: SimpleNamespace(gemini_api_key="k", active_semester="fall-2026"))
    app.dependency_overrides[route.get_member_store] = FakeMembers
    app.dependency_overrides[route.get_task_store] = FakeTasks
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_candidates_endpoint_excludes_current_assignee(client, monkeypatch):
    seen = {}

    async def fake_suggest(task, members, current, loads, settings):
        seen.update(current=current, pool=[m["code"] for m in members])
        return [{"code": "B", "fit": "strong"}]

    monkeypatch.setattr(route, "suggest_candidates", fake_suggest)
    body = client.get("/api/members/candidates/00000000-0000-0000-0000-000000000001").json()
    assert body["success"] and body["data"] == [{"code": "B", "fit": "strong"}]
    assert seen["current"] == ["A"] and body["meta"]["current_assignees"] == ["A"]


def test_candidates_need_a_gemini_key(client, monkeypatch):
    monkeypatch.setattr(route, "Settings", lambda: SimpleNamespace(gemini_api_key=None, active_semester="fall-2026"))
    assert client.get("/api/members/candidates/00000000-0000-0000-0000-000000000001").status_code == 503


def test_suggest_candidates_never_offers_current_assignee(monkeypatch):
    task_matching._cache.clear()
    sent = {}

    class Response:
        text = '[{"code": "B", "fit": "strong", "reason": "r", "matched_skills": ["budgeting"]}]'

    async def generate_content(**kwargs):
        sent.update(kwargs)
        return Response()

    fake = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(task_matching, "gemini_client", lambda key: fake)
    members = [{"code": c, **m} for c, m in MEMBERS.items()]
    import asyncio
    result = asyncio.run(task_matching.suggest_candidates(
        {"id": "t1", "title": "Order snacks"}, members, ["A"], {},
        SimpleNamespace(gemini_api_key="k", gemini_model="gemini-3.8-flash")))
    schema_codes = sent["config"].response_json_schema["items"]["properties"]["code"]["enum"]
    assert "A" not in schema_codes and [c["code"] for c in result] == ["B"]
