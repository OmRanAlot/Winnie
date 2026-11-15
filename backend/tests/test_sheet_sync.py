"""Live tracker reads, three-way conflicts, stale previews, worker policy and admin access."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.cli.sync_sheets import cycle
from app.core.settings import Settings
from app.integrations.google_sheets import GoogleSheetsReader, SheetSnapshot, SheetsUnavailable
from app.main import app
from app.routes.sheet_sync import get_sync_service
from app.schemas.sheets import SheetSource
from app.services.sheet_sync import SheetSyncService, merge_plan
from app.services.tracker_import import TrackerContext, preview_tracker
from app.services.tracker_sync import SHEET_FIELDS, ImportConflict

SOURCE = SheetSource(key='fall-board', spreadsheet_id='demo-sheet', semester_code='fall-2026', tab_id=7)
CSV = ('Event,Task Name,Status,Priority,Assignee,Deadline,Notes,Winnie Task ID\n'
       'Workshop,Book room,Upcoming,Normal,Alice,10/20/2026,,FALL26-001\n')


def preview(text=CSV, tab='October 2026'):
    return preview_tracker(text, TrackerContext(semester_code='fall-2026', spreadsheet_id='demo-sheet',
                                               tab_name=tab, tab_id='7'))


class Tasks:
    def __init__(self, rows=None):
        self.rows = rows or []

    def tracker_tasks(self, _):
        return deepcopy(self.rows)


def stored():
    task = preview()['rows'][0]['task']
    return {**task, 'id': '11111111-1111-4111-8111-111111111111', 'updated_at': '2026-11-01T12:00:00Z'}


def baseline(row):
    return {'FALL26-001': {'version': 1, 'source_values': {f: row[f] for f in SHEET_FIELDS}}}


def plan(rows, states, text=CSV, resolutions=None, tab='October 2026'):
    return merge_plan(preview(text, tab), Tasks(rows), states, 'https://test.supabase.co', 'fall-board', resolutions)


def test_new_and_repeated_source_import_use_permanent_identity():
    assert plan([], {})['summary']['insert'] == 1
    row = stored()
    assert plan([row], baseline(row))['summary']['unchanged'] == 1


def test_config_rejects_duplicate_sources_and_monthly_copies():
    with pytest.raises(ValueError, match='keys must be unique'):
        Settings(_env_file=None, sheet_sync_sources=[SOURCE, SOURCE])
    with pytest.raises(ValueError, match='one active tab'):
        Settings(_env_file=None, sheet_sync_sources=[SOURCE, SOURCE.model_copy(update={'key': 'other', 'tab_id': 8})])


def test_sheet_unchanged_preserves_completion_and_locally_edited_notes():
    row = stored()
    states = baseline(row)
    row.update(status='done', notes='Private local notes')
    result = plan([row], states)
    assert result['summary']['update'] == 0
    assert result['conflicts'] == []
    assert {'source_task_id': 'FALL26-001', 'field': 'status'} in result['preserved']
    assert 'notes' not in result['operations'][0]['values']


def test_source_change_applies_when_local_value_matches_last_sync():
    row = stored()
    result = plan([row], baseline(row), CSV.replace('Book room', 'Confirm room'))
    assert result['operations'][0]['values'] == {'title': 'Confirm room'}


def test_both_sides_changed_requires_an_explicit_resolution():
    row = stored()
    states = baseline(row)
    row['status'] = 'done'
    changed = CSV.replace('Upcoming', 'In Progress')
    result = plan([row], states, changed)
    assert result['conflicts'][0]['key'] == 'FALL26-001:status'
    kept = plan([row], states, changed, {'FALL26-001:status': 'winnie'})
    assert not kept['conflicts'] and kept['operations'][0]['values'] == {}
    accepted = plan([row], states, changed, {'FALL26-001:status': 'sheet'})
    assert accepted['operations'][0]['values']['status'] == 'in_progress'
    assert kept['plan_id'] != accepted['plan_id']


def test_bootstrap_does_not_overwrite_existing_csv_import_edits():
    row = stored()
    row['status'] = 'done'
    assert plan([row], {})['conflicts'][0]['field'] == 'status'


def test_month_rollover_preserves_identity_and_old_tabs_are_rejected():
    row = stored()
    result = plan([row], baseline(row), tab='November 2026')
    assert result['summary'] == {'insert': 0, 'update': 1, 'unchanged': 0}
    assert result['operations'][0]['values']['snapshot_month'] == '2026-11'
    with pytest.raises(ImportConflict):
        plan([row], baseline(row), tab='OLD October 2026')
    row['snapshot_month'] = '2026-11'
    with pytest.raises(ImportConflict):
        plan([row], baseline(row))


class Session:
    def __init__(self, *, title="October 2026", locale='en_US', status=200):
        self.calls = []
        self.title, self.locale, self.status = title, locale, status

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = {'properties': {'locale': self.locale}, 'sheets': [
            {'properties': {'sheetId': 7, 'title': self.title, 'sheetType': 'GRID'}}]}
        if '/values/' in url:
            payload = {'values': [
                ['Task Name', 'Deadline', 'Notes'], ['Book room', '10/20/2026'],
            ]}
        return SimpleNamespace(status_code=self.status, json=lambda: payload, raise_for_status=lambda: None)


def test_google_reader_uses_verified_tab_gid_and_pads_omitted_trailing_cells():
    session = Session(title="October's 2026")
    result = GoogleSheetsReader(SimpleNamespace(), session).read(SOURCE)
    assert result.tab_id == '7'
    assert result.text.splitlines()[1] == 'Book room,10/20/2026,'
    assert 'October%27%27s%202026' in session.calls[1][0]
    assert session.calls[1][1]['timeout'] == 30


@pytest.mark.parametrize('kwargs', [{'title': 'OLD October 2026'}, {'locale': 'en_GB'}, {'status': 403}])
def test_reader_rejects_archives_ambiguous_dates_and_denied_access(kwargs):
    with pytest.raises(SheetsUnavailable):
        GoogleSheetsReader(SimpleNamespace(), Session(**kwargs)).read(SOURCE)


def service(text=CSV):
    settings = SimpleNamespace(sheet_sync_sources=[SOURCE], supabase_url='https://test.supabase.co')
    store = SimpleNamespace(baselines=lambda _: {}, apply=lambda p: p['summary'], last_run=lambda _: None)
    return SheetSyncService(settings, SimpleNamespace(read=lambda _: SheetSnapshot(text, 'October 2026', '7')),
                            Tasks(), store)


def test_apply_rereads_source_and_rejects_stale_preview():
    sync = service()
    initial = sync.preview('fall-board')
    assert sync.apply('fall-board', initial['plan_id'])['insert'] == 1
    sync.reader.read = lambda _: SheetSnapshot(CSV.replace('Book room', 'Changed'), 'October 2026', '7')
    with pytest.raises(ImportConflict, match='preview changed'):
        sync.apply('fall-board', initial['plan_id'])


def test_worker_requires_both_apply_flag_and_source_opt_in():
    sync = service()
    assert cycle(sync, apply=True)[0]['mode'] == 'preview'
    sync.settings.sheet_sync_sources = [SOURCE.model_copy(update={'auto_apply': True})]
    assert cycle(sync)[0]['mode'] == 'preview'
    assert cycle(sync, apply=True)[0]['mode'] == 'applied'


def test_sync_routes_are_admin_only_and_apply_requires_review(signed_in_member, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_sync_service, service)
    with TestClient(app) as client:
        assert client.get('/api/sheet-sync/sources').status_code == 200
        assert client.post('/api/sheet-sync/fall-board/apply', json={}).status_code == 422
        assert client.post('/api/sheet-sync/fall-board/preview', json={}).status_code == 200
        signed_in_member.profile['is_admin'] = False
        for path, method, kwargs in [('/api/sheet-sync/sources', 'get', {}),
                                     ('/api/sheet-sync/fall-board/preview', 'post', {'json': {}}),
                                     ('/api/sheet-sync/fall-board/apply', 'post', {'json': {}})]:
            assert getattr(client, method)(path, **kwargs).status_code == 403
