"""Dashboard HTTP contracts, persistent round trips and authorization boundaries."""

import pytest
from fastapi.testclient import TestClient

from app.integrations.supabase import StorageUnavailable
from app.main import app
from app.routes.dashboard import get_dashboard_store
from app.services.dashboard import DashboardNotFound


class Store:
    def __init__(self):
        self.edits = {}
        self.evaluations = {}
        self.drafts = {}

    def edit_member(self, code, changes):
        if code == "missing":
            raise DashboardNotFound
        self.edits[code] = changes
        return changes

    def evaluation(self, code):
        return self.evaluations.get(code, {"comments": ""})

    def save_evaluation(self, code, comments, reviewer):
        value = {"member_code": code, "comments": comments, "reviewer_id": reviewer}
        self.evaluations[code] = value
        return value

    def draft(self, profile):
        return self.drafts.get(profile)

    def save_draft(self, profile, form):
        self.drafts[profile] = form
        return form

    def dependencies(self):
        return [{"task_id": "one", "depends_on_id": "two"}]


@pytest.fixture
def board(signed_in_member, monkeypatch):
    store = Store()
    monkeypatch.setitem(app.dependency_overrides, get_dashboard_store, lambda: store)
    with TestClient(app) as client:
        yield client, store, signed_in_member


def test_admin_form_writes_survive_followup_reads(board):
    client, store, principal = board
    body = {"display_name": "Updated Member", "board_role": "Secretary", "skills": ["Python"]}
    response = client.patch('/api/dashboard/members/A', json=body)
    assert response.status_code == 403 and 'approved roster' in response.json()['detail']
    assert store.edits == {}, 'Even administrators must not overwrite the approved roster through the app'
    assert client.put('/api/dashboard/evaluations/A', json={"comments": "Good follow-through"}).status_code == 200
    assert client.get('/api/dashboard/evaluations/A').json()['data']['comments'] == 'Good follow-through'
    assert store.evaluations['A']['reviewer_id'] == principal.user_id
    draft = {"title": "Workshop", "startDate": "2026-11-20", "dueDate": "2026-11-21", "ownerCode": "A"}
    assert client.put('/api/dashboard/draft', json=draft).status_code == 200
    assert client.get('/api/dashboard/draft').json()['data']['title'] == 'Workshop'
    # Personal drafts cannot be fetched by supplying another person's ID in the payload.
    assert client.put('/api/dashboard/draft', json={**draft, 'profile_id': 'someone-else'}).status_code == 422


def test_members_cannot_edit_profiles_or_read_admin_feedback(board):
    client, store, principal = board
    principal.profile['is_admin'] = False
    assert client.patch('/api/dashboard/members/A', json={'skills': ['Python']}).status_code == 403
    assert client.get('/api/dashboard/evaluations/A').status_code == 403
    assert client.put('/api/dashboard/evaluations/A', json={'comments': 'Denied'}).status_code == 403
    assert client.get('/api/dashboard/draft').status_code == 403
    assert client.get('/api/dashboard/dependencies').json()['data'] == store.dependencies()
    assert store.edits == {} and store.evaluations == {}


def test_validation_and_storage_failures_do_not_report_success(board):
    client, store, _principal = board
    for body in ({'is_admin': True}, {'email': 'other@example.com'}, {}, {'skills': [None]}):
        assert client.patch('/api/dashboard/members/A', json=body).status_code == 403
    assert client.put('/api/dashboard/draft', json={'startDate': '2026-11-22', 'dueDate': '2026-11-20'}).status_code == 422
    assert client.patch('/api/dashboard/members/missing', json={'display_name': 'Name'}).status_code == 403
    def unavailable():
        raise StorageUnavailable
    store.dependencies = unavailable
    result = client.get('/api/dashboard/dependencies')
    assert result.status_code == 503 and result.json()['success'] is False


def test_empty_personal_draft_is_not_a_fake_saved_form(board):
    client, _, _ = board
    assert client.get('/api/dashboard/draft').json()['data'] is None
