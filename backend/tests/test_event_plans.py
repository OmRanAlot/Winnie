"""HTTP permissions, revision contracts, validation and sanitized storage failures."""
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.integrations.supabase import StorageUnavailable
from app.main import app
from app.routes.event_plans import get_event_plan_store

ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def board(signed_in_member, monkeypatch):
    class Store:
        def __init__(self):
            self.calls = []

        def call(self, *args):
            self.calls.append(args)
            return {"id": ID, "revision": 1, "status": "draft", "payload": args[-1]}

    store = Store()
    monkeypatch.setitem(app.dependency_overrides, get_event_plan_store, lambda: store)
    with TestClient(app) as client:
        yield client, store, signed_in_member


def proposal():
    return {"event_name": "Synthetic workshop", "event_date": "2027-04-20", "tasks": [{
        "id": "room", "title": "Book room", "owner_code": "OWNER", "due_date": "2027-04-10",
        "rationale": "A room is needed.",
    }]}


def test_drafts_and_reviews_use_server_actor_and_exact_revision(board):
    client, store, actor = board
    assert client.post('/api/event-plans', json=proposal()).status_code == 201
    assert store.calls[-1][0] == actor.user_id
    assert store.calls[-1][-1]['semester_code']
    assert client.put(f'/api/event-plans/{ID}', json={**proposal(), 'expected_revision': 3}).status_code == 200
    assert store.calls[-1][1:4] == ('update', UUID(ID), 3)
    assert client.post(f'/api/event-plans/{ID}/review', json={
        'expected_revision': 3, 'decision': 'approved',
    }).status_code == 200
    assert store.calls[-1][1] == 'approved'
    assert client.post(f'/api/event-plans/{ID}/review', json={'decision': 'approved'}).status_code == 422


@pytest.mark.parametrize('method,path,body', [
    ('get', '/api/event-plans', None), ('get', f'/api/event-plans/{ID}', None),
    ('post', '/api/event-plans', proposal()),
    ('put', f'/api/event-plans/{ID}', {**proposal(), 'expected_revision': 1}),
    ('post', f'/api/event-plans/{ID}/review', {'expected_revision': 1, 'decision': 'approved'}),
])
def test_members_cannot_read_or_manage_administrator_proposals(board, method, path, body):
    client, store, actor = board
    actor.profile['is_admin'] = False
    assert client.request(method, path, json=body).status_code == 403
    assert store.calls == []


def test_service_actor_and_privilege_claims_are_rejected(board):
    client, store, actor = board
    assert client.post('/api/event-plans', json={**proposal(), 'status': 'approved'}).status_code == 422
    actor.service = True
    assert client.post('/api/event-plans', json=proposal()).status_code == 403
    assert store.calls == []


@pytest.mark.parametrize('invalid', ['cycle', 'missing', 'date', 'duplicate'])
def test_invalid_graph_and_dates_never_reach_storage(board, invalid):
    client, store, _ = board
    plan = proposal()
    if invalid == 'cycle':
        plan['tasks'][0]['dependency_ids'] = ['room']
    elif invalid == 'missing':
        plan['tasks'][0]['dependency_ids'] = ['unknown']
    elif invalid == 'date':
        plan['tasks'][0]['due_date'] = '2027-04-21'
    else:
        plan['tasks'] *= 2
    assert client.post('/api/event-plans', json=plan).status_code == 422
    assert store.calls == []


def test_conflicts_and_storage_failure_are_visible(board, monkeypatch):
    client, store, _ = board
    def conflict(*args):
        raise HTTPException(409, 'Plan changed')
    monkeypatch.setattr(store, 'call', conflict)
    assert client.post(f'/api/event-plans/{ID}/review', json={
        'expected_revision': 1, 'decision': 'approved',
    }).status_code == 409
    def unavailable(*args):
        raise StorageUnavailable('private provider details')
    monkeypatch.setattr(store, 'call', unavailable)
    response = client.get('/api/event-plans')
    assert response.status_code == 503 and 'private provider' not in response.text
