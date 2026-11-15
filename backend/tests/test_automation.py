"""Cloud Scheduler identity, leased scans and admin nudges; all providers are synthetic."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.integrations.photon import PhotonUnavailable
from app.integrations.supabase import StorageUnavailable
from app.main import app
from app.routes import automation
from app.schemas.sheets import SheetSource

TASK = '11111111-1111-4111-8111-111111111111'


@pytest.fixture
def board(signed_in_member, monkeypatch):
    class Store:
        def __init__(self):
            self.calls, self.results, self.busy = [], [], False

        def rpc(self, name, **values):
            self.calls.append((name, values))
            return {'queued': 1} if name == 'nudge_task' else {'overdue_queued': 1, 'dependency_queued': 1}

        def claim(self, key):
            return None if self.busy else 'claim-token'

        def finish(self, *args):
            self.results.append(args)

        def status(self):
            return {'jobs': [], 'notifications': {}}

    store = Store()
    queue = SimpleNamespace(enqueue=lambda: None)
    monkeypatch.setitem(app.dependency_overrides, automation.get_automation_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, automation.get_notification_queue, lambda: queue)
    monkeypatch.setenv('WINNIE_NOTIFICATIONS_ENABLED', 'true')
    monkeypatch.setenv('WINNIE_PHOTON_ENABLED', 'true')
    monkeypatch.setenv('WINNIE_REMINDERS_ENABLED', 'true')
    monkeypatch.setenv('WINNIE_SCHEDULER_SERVICE_ACCOUNT', 'scheduler@example.iam.gserviceaccount.com')
    monkeypatch.setenv('WINNIE_SCHEDULER_AUDIENCE', 'https://api.example.run.app')

    def verify(token, request, audience):
        assert audience == 'https://api.example.run.app'
        if token != 'google-scheduler-token':
            raise ValueError('bad signature')
        return {'email': 'scheduler@example.iam.gserviceaccount.com', 'email_verified': True}

    monkeypatch.setattr(automation.id_token, 'verify_oauth2_token', verify)
    with TestClient(app) as client:
        yield client, store, queue, signed_in_member


def test_nudge_requires_real_admin_and_returns_queue_warning_after_commit(board, monkeypatch):
    client, store, queue, actor = board
    actor.profile['is_admin'] = False
    assert client.post(f'/api/notifications/tasks/{TASK}/nudge').status_code == 403
    assert not store.calls
    actor.profile['is_admin'] = True
    def offline():
        raise PhotonUnavailable('synthetic')
    queue.enqueue = offline
    response = client.post(f'/api/notifications/tasks/{TASK}/nudge')
    assert response.status_code == 200 and response.json()['data']['queued'] == 1
    assert 'outbox' in response.json()['data']['notification_warning']
    assert store.calls[0][1]['p_actor'] == actor.user_id
    actor.service = True
    assert client.post(f'/api/notifications/tasks/{TASK}/nudge').status_code == 403


def test_scheduler_rejects_anonymous_and_dashboard_tokens_before_any_work(board):
    client, store, _, _ = board
    for headers in ({}, {'Authorization': 'Bearer dashboard-token'}):
        assert client.post('/api/internal/automation/reminders', headers=headers).status_code == 401
    assert not store.results and not store.calls


@pytest.mark.parametrize('claims', [
    {'email': 'wrong@example.com', 'email_verified': True},
    {'email': 'scheduler@example.iam.gserviceaccount.com', 'email_verified': False},
])
def test_scheduler_requires_expected_verified_service_account(board, monkeypatch, claims):
    client, store, _, _ = board
    monkeypatch.setattr(automation.id_token, 'verify_oauth2_token', lambda *a, **kw: claims)
    assert client.post('/api/internal/automation/reminders', headers={'Authorization': 'Bearer forged'}).status_code == 403
    assert not store.calls


def test_reminder_scan_has_lease_records_failures_and_queues_durable_delivery(board, monkeypatch):
    client, store, _, _ = board
    scans = []
    monkeypatch.setattr(automation, 'scan_reminders', lambda *a, **kw: scans.append(kw) or {'eligible': 1})
    headers = {'Authorization': 'Bearer google-scheduler-token'}
    assert client.post('/api/internal/automation/reminders', headers=headers).status_code == 200
    assert scans == [{'write': True}] and store.results[-1][2] == 'succeeded'
    store.busy = True
    assert client.post('/api/internal/automation/reminders', headers=headers).status_code == 409
    store.busy = False
    def failure(*a, **kw):
        raise StorageUnavailable('private details')
    monkeypatch.setattr(automation, 'scan_reminders', failure)
    response = client.post('/api/internal/automation/reminders', headers=headers)
    assert response.status_code == 503 and 'private details' not in response.text
    assert store.results[-1][2] == 'failed'


def test_sheets_runner_applies_only_opted_in_sources_and_surfaces_conflicts(board, monkeypatch):
    client, store, _, _ = board
    sources = [SheetSource(key='automatic', spreadsheet_id='sheet-automatic', semester_code='fall-2026', tab_name='October', auto_apply=True),
               SheetSource(key='manual', spreadsheet_id='sheet-manual', semester_code='fall-2026', tab_name='October', auto_apply=False)]
    applied, previews = [], []
    service = SimpleNamespace(settings=SimpleNamespace(sheet_sync_sources=sources), source=lambda key: next(s for s in sources if s.key == key))
    service.preview = lambda key: previews.append(key) or {'plan_id': 'preview-hash', 'summary': {'update': 1}, 'conflicts': [], 'preserved': []}
    service.apply = lambda key, expected: applied.append((key, expected)) or {'update': 1}
    monkeypatch.setitem(app.dependency_overrides, automation.get_sync_service, lambda: service)
    headers = {'Authorization': 'Bearer google-scheduler-token'}
    assert client.post('/api/internal/automation/sheets', headers=headers).status_code == 200
    assert previews == ['automatic'] and applied == [('automatic', 'preview-hash')]
    service.preview = lambda key: {'plan_id': 'hash', 'summary': {}, 'conflicts': ['local-edit'], 'preserved': []}
    assert client.post('/api/internal/automation/sheets', headers=headers).status_code == 200
    assert store.results[-1][2] == 'conflict' and len(applied) == 1


def test_status_is_admin_only_and_reports_flags(board):
    client, _, _, actor = board
    response = client.get('/api/automation/status')
    assert response.status_code == 200 and response.json()['data']['scheduler_configured']
    actor.profile['is_admin'] = False
    assert client.get('/api/automation/status').status_code == 403


@pytest.mark.parametrize('kind', ['task', 'deadline'])
async def test_photon_worker_drains_queued_notices_without_rescanning(monkeypatch, kind):
    from app.routes import photon

    monkeypatch.setenv('WINNIE_HELP_WORKFLOW_ENABLED', 'false')
    monkeypatch.setenv('WINNIE_NOTIFICATIONS_ENABLED', 'true')
    monkeypatch.setenv('WINNIE_REMINDERS_ENABLED', 'true' if kind == 'deadline' else 'false')
    monkeypatch.setattr(photon, 'datetime', SimpleNamespace(now=lambda zone: SimpleNamespace(hour=12)))
    notices = [{'id': TASK, 'claim_token': 'token', 'recipient': 'one@example.com', 'text': 'Synthetic notice'}]
    calls, finished = [], []

    def rpc(name, **values):
        calls.append((name, values))
        if name == 'claim_task_notification' and kind == 'task':
            return notices.pop() if notices else None
        return None

    monkeypatch.setattr(photon, 'HelpRequestStore', lambda: SimpleNamespace(rpc=rpc))
    monkeypatch.setattr(photon, 'ReminderStore', lambda: SimpleNamespace(finish=lambda *args: finished.append(args)))

    def next_delivery(*args, **kwargs):
        assert kwargs == {'scan': False}
        return {'delivery': notices.pop() if notices else None}

    monkeypatch.setattr(photon, 'next_reminder', next_delivery)
    sender = SimpleNamespace(send=AsyncMock(return_value='provider-receipt'))
    assert await photon.dispatch_notifications(sender) is False
    sender.send.assert_awaited_once()
    if kind == 'task':
        assert any(name == 'finish_task_notification' and values['p_outcome'] == 'sent' for name, values in calls)
    else:
        assert finished[0][2:4] == ('sent', 'provider-receipt')
