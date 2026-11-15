"""GET /api/members and /api/members/assignments with synthetic members; no Supabase calls."""

import pytest
from fastapi.testclient import TestClient

from app.integrations.supabase import StorageUnavailable
from app.main import app
from app.routes import members as route
from app.services.members import AliasConflict, MemberStore, task_assignments


def test_explicit_owner_takes_precedence_over_imported_assignment_text():
    tasks = [{"id": "reassigned", "owner_code": "NEW_MEMBER", "assignee_text": "Old Name"}]
    assert task_assignments(tasks, []) == {"reassigned": ["NEW_MEMBER"]}


ALIASES = [
    {"alias": "Avery Chen", "member_code": "AVERY"},
    {"alias": "avery@example.test", "member_code": "AVERY"},
    {"alias": "Morgan Lee", "member_code": "MORGAN"},
]
PUBLIC = {"code": "AVERY", "display_name": "Avery Chen", "board_role": "Treasurer",
          "role_description": "Money", "skills": []}


class Members:
    def __init__(self, fail=False, aliases=ALIASES):
        self.fail, self._aliases = fail, aliases

    def list_active(self):
        if self.fail:
            raise StorageUnavailable("down")
        return [PUBLIC]

    def previous_roles(self):
        return {}

    def aliases(self, semester):
        assert semester == "fall-2026"
        return self._aliases


class Tasks:
    def __init__(self, count=3):
        self.rows = [
            {"id": "t1", "assignee_text": "Avery Chen"},
            {"id": "t2", "assignee_text": "avery@example.test Morgan Lee"},
            {"id": "t3", "assignee_text": "Someone Unknown"},
        ] + [{"id": f"x{i}", "assignee_text": ""} for i in range(count - 3)]
        self.calls = []

    def list(self, *, semester_code=None, limit=50, offset=0, **_):
        self.calls.append(offset)
        return self.rows[offset:offset + limit], len(self.rows)


SKILLS = {"AVERY": {"technical": [{"skill": "budgeting", "evidence": "Money"}],
                    "soft": [{"skill": "follow-up", "evidence": "Money"}], "source": "role-derived"}}


@pytest.fixture
def client(monkeypatch, signed_in_member):
    # Never read the developer's real backend/data/member_skills.json in tests.
    monkeypatch.setattr(route, "load_skills", lambda: SKILLS)
    monkeypatch.setattr(route, "load_previous_roles", dict)
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(members=None, tasks=None):
    app.dependency_overrides[route.get_member_store] = lambda: members or Members()
    app.dependency_overrides[route.get_task_store] = lambda: tasks or Tasks()


def test_members_returns_public_fields_only(client):
    use()
    body = client.get("/api/members").json()
    assert body["success"] and body["meta"] == {"total": 1}
    assert body["data"] == [{**PUBLIC, "skills": ["budgeting", "follow-up"], "technical_skills": ["budgeting"],
                             "soft_skills": ["follow-up"], "skills_source": "role-derived",
                             "previous_roles": [], "previous_role_skills": [], "previous_roles_source": None}]
    assert not {"email", "phone_number"} & set(body["data"][0])


def test_list_active_never_selects_contact_details():
    assert "email" not in MemberStore.PUBLIC_FIELDS and "phone" not in MemberStore.PUBLIC_FIELDS


def test_members_storage_down_is_503(client):
    use(members=Members(fail=True))
    response = client.get("/api/members")
    assert response.status_code == 503 and response.json()["success"] is False


def test_assignments_resolve_verified_aliases_and_flag_unknowns(client):
    use()
    body = client.get("/api/members/assignments").json()
    assert body["data"] == {"t1": ["AVERY"], "t2": ["AVERY", "MORGAN"], "t3": None}
    assert body["meta"]["unresolved"] == 1 and body["meta"]["aliases"] == 3


def test_assignments_page_through_all_tasks(client):
    tasks = Tasks(count=205)
    use(tasks=tasks)
    body = client.get("/api/members/assignments").json()
    assert body["meta"]["tasks"] == 205 and tasks.calls == [0, 100, 200]


def test_ambiguous_aliases_are_409(client):
    use(members=Members(aliases=ALIASES + [{"alias": "Avery Chen", "member_code": "OTHER"}]))
    assert client.get("/api/members/assignments").status_code == 409


def test_empty_assignee_is_no_one_not_unknown():
    assert task_assignments([{"id": 1, "assignee_text": "  "}], ALIASES) == {"1": []}
    with pytest.raises(AliasConflict):
        task_assignments([{"id": 1, "assignee_text": "x"}], [{"alias": " ", "member_code": "A"}])
