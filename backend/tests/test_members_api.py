"""GET /api/members and /api/members/assignments with synthetic members; no Supabase calls."""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import Principal, get_principal
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


class Roster(Members):
    def __init__(self):
        super().__init__()
        self.rows = [{"code": "AVERY", "display_name": "Avery Chen", "active": True,
                      "email": "avery@example.test", "phone_number": None,
                      "board_role": "Treasurer", "contact_consent": True}]
        self.calls = []

    def list_roster(self):
        return self.rows

    def save_roster_member(self, actor, code, semester, fields, *, create):
        self.calls.append((actor, semester, create, fields))
        return {"code": code, **fields}


def test_roster_contacts_are_private_and_uncached(client):
    use(members=Roster())
    response = client.get("/api/members/roster")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json()["data"][0]["email"] == "avery@example.test"


@pytest.mark.parametrize(("admin", "service"), [(False, False), (True, True)])
def test_roster_list_and_writes_require_a_signed_in_administrator(client, admin, service):
    roster = Roster()
    use(members=roster)
    actor = Principal("any", {"is_admin": admin, "password_setup_complete": True}, service)
    app.dependency_overrides[get_principal] = lambda: actor
    assert client.get("/api/members/roster").status_code == 403
    assert client.post("/api/members/roster", json={"display_name": "Morgan"}).status_code == 403
    assert client.patch("/api/members/roster/AVERY", json={"active": False}).status_code == 403
    assert not roster.calls


class MessagingContacts:
    def __init__(self):
        self.identities = [
            {"platform": "imessage", "sender_id": "+12025550123", "member_code": "AVERY"},
        ]

    def list_identities(self):
        return list(self.identities)

    def ensure_identity(self, member_code, sender_id):
        row = {"platform": "imessage", "sender_id": sender_id, "member_code": member_code}
        self.identities.append(row)
        return row


def test_messaging_contacts_lists_board_phones_for_admins(client, monkeypatch):
    roster = Roster()
    roster.rows[0]["phone_number"] = "(202) 555-0123"
    contacts = MessagingContacts()
    use(members=roster)
    app.dependency_overrides[route.get_messaging_contacts] = lambda: contacts
    monkeypatch.setattr(route, "sync_board_phones", lambda *args, **kwargs: {
        "mode": "shared", "lines": [], "total": 1, "ready": 1,
        "contacts": [{"member_code": "AVERY", "handle": "+12025550123", "ready": True, "errors": []}],
    })
    listed = client.get("/api/members/messaging-contacts")
    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert listed.json()["data"][0]["handle"] == "+12025550123"
    assert listed.json()["meta"]["ready"] == 1
    synced = client.post("/api/members/messaging-contacts/sync", json={
        "enroll_photon": False, "rotate_across_lines": True,
    })
    assert synced.status_code == 200
    assert synced.json()["meta"]["ready"] == 1


def test_roster_normalizes_contacts_and_preserves_fields_omitted_from_patch(client):
    roster = Roster()
    use(members=roster)
    created = client.post("/api/members/roster", json={
        "display_name": " Morgan Lee ", "board_role": " Treasurer ", "email": " MORGAN@EXAMPLE.TEST ",
        "phone_number": " (202) 555-0123 ", "contact_consent": True,
    })
    assert created.status_code == 201
    assert created.json()["data"]["code"].startswith("WICS_")
    assert roster.calls[-1][1:] == ("fall-2026", True, {
        "display_name": "Morgan Lee", "board_role": "Treasurer", "email": "morgan@example.test",
        "phone_number": "(202) 555-0123", "contact_consent": True,
    })
    response = client.patch("/api/members/roster/AVERY", json={"board_role": "", "phone_number": None})
    assert response.status_code == 200
    assert roster.calls[-1][2:] == (False, {"board_role": "", "phone_number": None})
    for fields in [{"is_admin": True}, {"phone_number": "1234"}, {"display_name": None},
                   {"email": "missing-at-sign"}]:
        assert client.patch("/api/members/roster/AVERY", json=fields).status_code == 422
    assert len(roster.calls) == 2
