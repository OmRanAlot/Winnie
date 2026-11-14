"""Validate the supplied attendance CSV and resolve headers against verified roster aliases."""
import csv
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.members import normalize_alias


def parse_attendance(path: Path, year: int, members: list[dict], aliases: list[dict],
                     mapping: dict[str, str] | None = None) -> list[dict]:
    lookup: dict[str, set[str]] = {}
    codes = {m['code'] for m in members}
    for name, code in ([(m['display_name'], m['code']) for m in members]
                       + [(a['alias'], a['member_code']) for a in aliases]):
        lookup.setdefault(normalize_alias(name), set()).add(code)
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = csv.reader(handle)
        header = next(rows, [])
        if len(header) < 3 or header[0] != 'Date' or header[-1] != 'Total':
            raise ValueError('Expected Date, member columns, Total.')
        resolved = []
        for name in header[1:-1]:
            matches = {mapping[name]} if mapping and name in mapping else lookup.get(normalize_alias(name), set())
            if len(matches) != 1 or not matches <= codes:
                raise ValueError(f'Provide an explicit member-code mapping for {name}.')
            resolved.append(next(iter(matches)))
        if len(set(resolved)) != len(resolved):
            raise ValueError('Multiple columns map to the same member.')
        records, dates = [], set()
        for line, row in enumerate(rows, 2):
            if not row or not row[0].strip():
                continue  # undated placeholders and the totals row are not meetings
            if len(row) != len(header):
                raise ValueError(f'Line {line}: unexpected number of columns.')
            month, day = map(int, row[0].strip().split('/'))
            meeting_date = date(year, month, day)
            if meeting_date in dates:
                raise ValueError(f'Line {line}: duplicate meeting date.')
            dates.add(meeting_date)
            flags = [v.strip().upper() for v in row[1:-1]]
            if any(v not in ('TRUE', 'FALSE') for v in flags):
                raise ValueError(f'Line {line}: expected TRUE/FALSE attendance.')
            attendees = [code for code, flag in zip(resolved, flags) if flag == 'TRUE']
            if int(row[-1]) != len(attendees):
                raise ValueError(f'Line {line}: total does not match attendance.')
            records.append({
                'held_at': datetime.combine(meeting_date, time(12), ZoneInfo('America/New_York')).isoformat(),
                'title': 'E-Board Meeting',
                'recording_id': f'attendance-csv:{meeting_date.isoformat()}',
                'attendees': attendees,
            })
    if not records:
        raise ValueError('No dated meetings found.')
    return records
