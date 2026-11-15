"""Attendance API authorization, CSV validation and roster matching with synthetic records."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.meetings import get_attendance_store
from app.services.attendance_import import parse_attendance


class Store:
    def __init__(self):
        self.saved = None

    def list_meetings(self):
        return [{'id': 1, 'attendees': ['A']}]

    def save(self, meeting, attendees):
        self.saved = (meeting, attendees)

    def create(self, title, held_at):
        return {'id': 2, 'title': title, 'held_at': held_at.isoformat()}


def test_admin_can_record_empty_attendance_but_member_cannot(signed_in_member, monkeypatch):
    store = Store()
    monkeypatch.setitem(app.dependency_overrides, get_attendance_store, lambda: store)
    with TestClient(app) as client:
        assert client.patch('/api/meetings/1/attendance', json={'attendees': []}).status_code == 200
        assert store.saved == (1, [])
        signed_in_member.profile['is_admin'] = False
        assert client.patch('/api/meetings/1/attendance', json={'attendees': ['A']}).status_code == 403
        assert client.post('/api/meetings', json={'title': 'Board', 'meeting_date': '2026-11-14'}).status_code == 403
        assert client.get('/api/meetings').json()['data'] == [{'id': 1, 'attendees': ['A']}]
        assert store.saved == (1, [])


def test_create_meeting_validates_date_and_title(signed_in_member, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_attendance_store, Store)
    with TestClient(app) as client:
        body = {'title': ' Board ', 'meeting_date': '2026-11-14'}
        response = client.post('/api/meetings', json=body)
        assert response.status_code == 200
        assert response.json()['data']['title'] == 'Board'
        assert response.json()['data']['held_at'] == '2026-11-14T12:00:00-05:00'
        assert client.post('/api/meetings', json={**body, 'title': '  '}).status_code == 422
        assert client.post('/api/meetings', json={**body, 'meeting_date': '11/14'}).status_code == 422


def test_anonymous_attendance_access_is_rejected(monkeypatch):
    monkeypatch.setenv('WINNIE_TASK_API_KEY', '')
    with TestClient(app) as client:
        assert client.get('/api/meetings').status_code == 401
        assert client.patch('/api/meetings/1/attendance', json={'attendees': []}).status_code == 401


def parse(path: Path, text: str, **kwargs):
    path.write_text(text)
    return parse_attendance(path, 2026, [{'code': 'A', 'display_name': 'Alice Example'}],
                            [{'alias': 'Alice', 'member_code': 'A'}], **kwargs)


def test_csv_ignores_undated_rows_and_preserves_zero_attendance(tmp_path):
    records = parse(tmp_path / 'source.csv', 'Date,Alice,Total\n9/3,TRUE,1\n9/10,FALSE,0\n,FALSE,0\n,1,\n')
    assert len(records) == 2
    assert records[0]['attendees'] == ['A']
    assert records[1]['attendees'] == []
    assert records[0]['recording_id'] == 'attendance-csv:2026-09-03'


@pytest.mark.parametrize('text', [
    'Date,Unknown,Total\n9/3,TRUE,1',
    'Date,Alice,Total\n9/3,TRUE,0',
    'Date,Alice,Total\n9/3,MAYBE,0',
    'Date,Alice,Total\n9/3,TRUE,1\n9/3,TRUE,1',
    'Date,Alice,Total\n2/30,TRUE,1',
])
def test_csv_rejects_unresolved_or_inconsistent_input(tmp_path, text):
    with pytest.raises(ValueError):
        parse(tmp_path / 'source.csv', text)


def test_csv_explicit_mapping_must_use_a_real_member(tmp_path):
    text = 'Date,Nickname,Total\n9/3,TRUE,1'
    assert parse(tmp_path / 'source.csv', text, mapping={'Nickname': 'A'})[0]['attendees'] == ['A']
    with pytest.raises(ValueError):
        parse(tmp_path / 'source.csv', text, mapping={'Nickname': 'UNKNOWN'})
