"""Previous board roles on profiles, and finding past holders of a role. No Supabase calls."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import members as route
from app.services.member_history import advisors_for, load_previous_roles, with_previous_roles

MEMBERS = [
    {"code": "T", "display_name": "Tia", "board_role": "Treasurer", "skills": []},
    {"code": "P", "display_name": "Pia", "board_role": "Public Relations Chair", "skills": []},
    {"code": "E", "display_name": "Eve", "board_role": "Event Coordinator", "skills": []},
]
SKILLS = {"P": {"technical": [{"skill": "graphic design", "evidence": "x"}], "soft": []},
          "E": {"technical": [{"skill": "event planning", "evidence": "x"}], "soft": []}}
HISTORY = {"T": ["Public Relations Chair"], "E": ["Event Coordinator"], "P": ["Fundraising Coordinator"]}


def test_previous_role_skills_come_from_the_current_holders_role():
    t, p, e = with_previous_roles(MEMBERS, HISTORY, {}, SKILLS)
    assert t["previous_roles"] == ["Public Relations Chair"] and t["previous_role_skills"] == ["graphic design"]
    assert e["previous_role_skills"] == []          # same role as now adds nothing new
    assert p["previous_role_skills"] == []          # role no longer exists: no invented skills
    assert t["previous_roles_source"] == "board-list"


def test_supabase_previous_roles_win_over_the_json():
    t, *_ = with_previous_roles(MEMBERS, HISTORY, {"T": ["Secretary"]}, SKILLS)
    assert t["previous_roles"] == ["Secretary"] and t["previous_roles_source"] == "supabase"


def test_advisors_are_past_holders_of_my_role_not_me():
    people = with_previous_roles(MEMBERS, HISTORY, {}, SKILLS)
    pr = next(m for m in people if m["code"] == "P")
    assert [a["code"] for a in advisors_for(pr, people)] == ["T"]
    eve = next(m for m in people if m["code"] == "E")
    assert advisors_for(eve, people) == []


def test_load_previous_roles_skips_the_note(tmp_path):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({"_note": "x", "A": {"name": "A", "previous_roles": [{"role": "Secretary"}]}}))
    assert load_previous_roles(f) == {"A": ["Secretary"]}
    assert load_previous_roles(tmp_path / "missing.json") == {}


def test_real_board_file_only_uses_known_role_names():
    known = {"President", "Vice President", "Secretary", "Treasurer", "Event Coordinator",
             "Industry Partnerships Chair", "Public Relations Chair", "Technical Director",
             "Membership Chair", "Community Outreach Chair", "Fundraising Coordinator"}
    roles = {r for rs in load_previous_roles().values() for r in rs}
    assert roles and roles <= known


class Store:
    def list_active(self):
        return [dict(m) for m in MEMBERS]

    def previous_roles(self):
        return {}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(route, "load_skills", lambda: SKILLS)
    monkeypatch.setattr(route, "load_previous_roles", lambda: HISTORY)
    app.dependency_overrides[route.get_member_store] = Store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_advisors_endpoint(client):
    body = client.get("/api/members/P/advisors").json()
    assert body["success"] and [a["code"] for a in body["data"]] == ["T"]
    assert body["meta"] == {"role": "Public Relations Chair", "total": 1}
    assert client.get("/api/members/NOPE/advisors").status_code == 404


def test_profiles_include_previous_roles(client):
    tia = next(m for m in client.get("/api/members").json()["data"] if m["code"] == "T")
    assert tia["previous_roles"] == ["Public Relations Chair"] and tia["previous_role_skills"] == ["graphic design"]
