"""Synthetic Photon metadata and fake storage; no external messages or model calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import messages
from app.services.conversation import HelpIntent
from app.services.members import resolve_member_choice
from app.services.messaging_reassignments import reassignment_reply


@pytest.mark.parametrize('text,expected', [
    ('Taylor Example', 'TARGET'), ('Taylor', 'TARGET'), ('1', 'TARGET'),
    ('choose Taylor Example please', 'TARGET'), ('select 2', 'OTHER'),
    ('Example', None), ('unknown', None), ('3', None),
])
def test_saved_suggestion_choice_uses_unique_name_or_displayed_number(text, expected):
    candidates = [{'code': 'TARGET', 'name': 'Taylor Example'}, {'code': 'OTHER', 'name': 'Alex Example'}]
    assert resolve_member_choice(text, candidates) == expected
    assert resolve_member_choice('Taylor', candidates + [{'code': 'SECOND', 'name': 'Taylor Other'}]) is None


class Members:
    def list_active(self):
        return [{'code':'TARGET','display_name':'Taylor Example'}]

    def resolve(self, platform, sender):
        return {'code': 'OWNER'} if sender == 'owner@example.com' else None


class Tasks:
    def by_task_code(self, code, semester):
        return {'id': '11111111-1111-4111-8111-111111111111', 'task_code': code}


class Store:
    def pending(self, message):
        return {'can_review':True,'requests':[{'request_no':8,'title':'Demo task','can_review':True,'can_respond':False}]}

    def __init__(self):
        self.calls = []

    def act(self, message, action, payload):
        self.calls.append((message.sender_id, message.message_id, action, payload))
        if action == 'list':
            return {'requests': [{'request_no': 8, 'task_code': 'WIN-202611-1', 'title': 'Demo task',
                'recipient_decision': 'pending', 'incoming': True}]}
        return {'request_no':8,'status':'approved' if action=='accepted' else 'pending','admin_decision':'approved' if action in ('approved','accepted') else 'pending','recipient_decision':'accepted' if action=='accepted' else 'pending'}


def message(text, **extra):
    return messages.IncomingMessage(**{'text': text, 'sender_id': 'owner@example.com',
        'platform': 'imessage', 'message_id': 'event-1', 'conversation_type': 'dm', **extra})


def settings():
    return SimpleNamespace(help_workflow_enabled=True, active_semester='fall-2026')


@pytest.mark.asyncio
async def test_commands_forward_verified_transport_metadata_and_exact_actions():
    store = Store()
    reply = await reassignment_reply(message('accept REQ-8'), Members(), Tasks(), store, settings())
    assert 'Ownership transferred' in reply
    assert store.calls == [('owner@example.com', 'event-1', 'accepted', {'request_no': 8})]
    assert 'admin approved' in await reassignment_reply(message('approve REQ-8'), Members(), Tasks(), store, settings())
    assert 'Demo task' in await reassignment_reply(message('requests'), Members(), Tasks(), store, settings())
    await reassignment_reply(message('reassign WIN-202611-1 to Taylor Example'), Members(), Tasks(), store, settings())
    assert store.calls[-1][2] == 'submit'
    assert store.calls[-1][3]['proposed_code'] == 'TARGET'
    assert 'actor' not in store.calls[-1][3]


@pytest.mark.asyncio
async def test_invalid_context_cannot_write_and_database_errors_never_claim_success():
    store = Store()
    for extra in ({'conversation_type': 'group'}, {'sender_id': 'stranger@example.com'}, {'message_id': None}):
        await reassignment_reply(message('accept REQ-8', **extra), Members(), Tasks(), store, settings())
    assert not store.calls
    def deny(*args):
        raise ValueError('Only the proposed recipient can respond')
    store.act = deny
    reply = await reassignment_reply(message('accept REQ-8'), Members(), Tasks(), store, settings())
    assert reply == 'Only the proposed recipient can respond'


def test_http_routes_text_commands_and_gemini_help_to_shared_workflow(monkeypatch):
    monkeypatch.setenv('WINNIE_MESSAGING_BRIDGE_SECRET', 'synthetic-secret')
    monkeypatch.setenv('WINNIE_HELP_WORKFLOW_ENABLED', 'true')
    store = Store()
    monkeypatch.setitem(app.dependency_overrides, messages.get_reassignment_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, messages.get_member_store, Members)
    monkeypatch.setitem(app.dependency_overrides, messages.get_task_store, Tasks)
    help_reply = AsyncMock(return_value='Saved HELP-1: choose a suggested recipient')
    monkeypatch.setattr(messages, 'help_workflow_reply', help_reply)
    monkeypatch.setattr(messages, 'conversation_reply', lambda *args: HelpIntent('WIN-202611-1'))
    with TestClient(app) as client:
        headers = {'X-Winnie-Bridge-Secret': 'synthetic-secret'}
        denied = client.post('/api/messages', json=message('accept REQ-8').model_dump())
        assert denied.status_code == 401 and not store.calls
        result = client.post('/api/messages', json=message('accept REQ-8').model_dump(), headers=headers)
        assert result.status_code == 200 and 'Ownership transferred' in result.json()['reply']
        help_reply.side_effect = [None, 'Saved HELP-1: choose a suggested recipient']
        result = client.post('/api/messages', json=message('I need a replacement for the demo task').model_dump(), headers=headers)
        assert result.json()['reply'].startswith('Saved HELP-1')
        assert help_reply.call_args.args[0].text == 'help WIN-202611-1'
        assert help_reply.call_args.args[0].sender_id == 'owner@example.com'

def test_notification_api_routes_shared_outbox_receipts_and_legacy_fallback(monkeypatch):
    from app.routes import help_requests
    monkeypatch.setenv('WINNIE_MESSAGING_BRIDGE_SECRET', 'synthetic-secret')
    monkeypatch.setenv('WINNIE_HELP_WORKFLOW_ENABLED', 'true')
    delivery = {'id': '11111111-1111-4111-8111-111111111111',
        'claim_token': '22222222-2222-4222-8222-222222222222', 'kind': 'dm',
        'recipient': 'target@example.com', 'text': 'Accept REQ-8'}
    class Outbox:
        def __init__(self):
            self.calls = []
            self.shared = delivery
        def rpc(self, name, **values):
            self.calls.append(name)
            if name == 'claim_reassignment_notification':
                return self.shared
            if name == 'claim_help_notification':
                return None
            if name == 'finish_reassignment_notification':
                return 'sent'
            raise AssertionError(name)
    outbox = Outbox()
    monkeypatch.setitem(app.dependency_overrides, help_requests.get_help_store, lambda: outbox)
    with TestClient(app) as client:
        headers = {'X-Winnie-Bridge-Secret': 'synthetic-secret'}
        assert client.post('/api/internal/help/next', json={}).status_code == 401
        result = client.post('/api/internal/help/next', json={}, headers=headers)
        assert result.json()['delivery'] == delivery
        assert outbox.calls == ['claim_reassignment_notification']
        result = client.post('/api/internal/help/result', json={'delivery_id': delivery['id'],
            'claim_token': delivery['claim_token'], 'outcome': 'sent', 'provider_id': 'synthetic-receipt'}, headers=headers)
        assert result.json()['status'] == 'sent'
        assert outbox.calls[-1] == 'finish_reassignment_notification'
        outbox.shared = None
        assert client.post('/api/internal/help/next', json={}, headers=headers).json()['delivery'] is None
        assert outbox.calls[-2:] == ['claim_reassignment_notification', 'claim_help_notification']
