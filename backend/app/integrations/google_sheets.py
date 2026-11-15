"""Read configured private trackers with read-only Google application credentials."""
import csv
import io
from dataclasses import dataclass
from urllib.parse import quote

import google.auth
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests.exceptions import RequestException

from app.services.tracker_import import snapshot_context

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
MAX_ROWS = 10000
MAX_COLUMNS = 52


class SheetsUnavailable(Exception):
    """Sanitized configuration/provider error safe to show on the admin dashboard."""


@dataclass
class SheetSnapshot:
    text: str
    tab_name: str
    tab_id: str


class GoogleSheetsReader:
    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session

    def _session(self):
        if self.session is not None:
            return self.session
        try:
            if self.settings.sheets_credentials_file:
                credentials = service_account.Credentials.from_service_account_file(
                    str(self.settings.sheets_credentials_file), scopes=SCOPES,
                )
            else:
                credentials, _ = google.auth.default(scopes=SCOPES)
            return AuthorizedSession(credentials)
        except (GoogleAuthError, OSError, ValueError) as exc:
            raise SheetsUnavailable('Configure Google application credentials or a Sheets service-account file.') from exc

    def read(self, source):
        session = self._session()
        base = f'https://sheets.googleapis.com/v4/spreadsheets/{quote(source.spreadsheet_id, safe="")}'
        try:
            meta = self._get(session, base, {
                'fields': 'properties(locale),sheets(properties(sheetId,title,sheetType))',
            })
            tabs = [s['properties'] for s in meta.get('sheets', [])]
            matches = [t for t in tabs if (
                t['sheetId'] == source.tab_id if source.tab_id is not None else t['title'] == source.tab_name
            )]
            if len(matches) != 1:
                raise SheetsUnavailable('Configured tab was not found. Check its name or gid.')
            tab = matches[0]
            if tab.get('sheetType', 'GRID') != 'GRID':
                raise SheetsUnavailable('Select a standard grid tab.')
            if snapshot_context(tab['title'])[0]:
                raise SheetsUnavailable('OLD tabs are archived. Select the active tracker tab.')
            if meta.get('properties', {}).get('locale') != 'en_US':
                raise SheetsUnavailable('Tracker locale must be United States so month/day deadlines are unambiguous.')
            # Quote tab names, including apostrophes; never let names become range expressions.
            a1 = "'" + tab['title'].replace("'", "''") + f"'!A1:BA{MAX_ROWS + 1}"
            payload = self._get(session, base + '/values/' + quote(a1, safe=''), {
                'majorDimension': 'ROWS', 'valueRenderOption': 'FORMATTED_VALUE',
            })
            rows = payload.get('values', [])
            if len(rows) > MAX_ROWS or any(len(row) > MAX_COLUMNS for row in rows):
                raise SheetsUnavailable('Tracker exceeds the supported 10,000 rows or 52 columns. Split the source.')
            header_index = next((i for i, row in enumerate(rows)
                                 if 'task name' in [str(c).strip().lower() for c in row]
                                 and 'deadline' in [str(c).strip().lower() for c in row]), None)
            if header_index is None:
                raise SheetsUnavailable('Expected tracker headers including Task Name and Deadline.')
            width = len(rows[header_index])
            stream = io.StringIO(newline='')
            writer = csv.writer(stream)
            for row in rows[header_index:]:
                # Google omits trailing empty cells; the CSV validator needs complete rows.
                writer.writerow([*row, *([''] * max(0, width - len(row)))])
            return SheetSnapshot(stream.getvalue(), tab['title'], str(tab['sheetId']))
        except (GoogleAuthError, RequestException, ValueError, KeyError, TypeError) as exc:
            raise SheetsUnavailable('Google Sheets could not be read. Check credentials, sharing and API access.') from exc
        finally:
            if self.session is None:
                session.close()

    @staticmethod
    def _get(session, url, params):
        response = session.get(url, params=params, timeout=30)
        if response.status_code in (401, 403):
            raise SheetsUnavailable('Google access was denied. Enable Sheets API and share this workbook with the configured account.')
        if response.status_code == 404:
            raise SheetsUnavailable('Workbook was not found or is not shared with the configured account.')
        response.raise_for_status()
        return response.json()
