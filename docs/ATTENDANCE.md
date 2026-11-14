# Meeting attendance

Admins can open **Admin Settings → Manage Meeting Attendance**, add a meeting with
a title and date, select attendees from the active board roster, and save. Existing
recorded meetings also appear in the selector. Members can read meeting history;
only admins can create meetings or update attendance. Writes replace the attendee
set in one database transaction. Saving an empty selection explicitly records zero
attendees; an unsaved meeting remains “Attendance not recorded.” Member attendance
counts and individual meeting histories use these saved records.

Apply `supabase/migrations/20261115110000_meeting_attendance.sql` after the existing
ordered migrations. All browser access uses the authenticated backend. The table
and write functions are restricted to the server's service role; the API checks
admin permissions before writes.

## Import the Fall 2026 CSV

The importer validates dated rows, TRUE/FALSE values, per-meeting totals and member
matches. Undated placeholders and the bottom totals row are ignored. Each header
must match a verified roster alias or an explicit mapping to a member code. It never
creates members or guesses from name substrings. Supply the year because the source
dates do not include one. Date-only meetings use local noon in America/New_York as
a storage convention, not a claim about their actual start time.

From `backend/`, preview with:

```powershell
.\.venv\Scripts\python.exe -m app.cli.import_attendance "C:/Users/shara/Downloads/E-Board Meeting Attendance Sheet Fall 26 - Sheet1.csv" --year 2026 --semester fall-2026 --mapping data/attendance-fall-2026-mapping.json
```

A mapping is a JSON object such as `{"Alice": "VERIFIED_MEMBER_CODE"}`; review each
mapping against the roster. For this attachment, the prepared local mapping uses
the matching full names, including **Darsha → Saidarsha Karunakaran**.

Append `--apply` to import through Supabase after applying the migration, or append
`--prepare-sql data/import-attendance-fall-2026.sql` to produce SQL for the Supabase
SQL Editor. Local `backend/data/` files are gitignored. The import is transactional
and repeatable: records are keyed by `attendance-csv:YYYY-MM-DD`, and meetings with
already recorded attendance are skipped so later admin edits survive a rerun.

The provided source has 10 dated meetings (September 3–November 12, 2026), 13 member
columns and 108 positive attendance marks. The prepared local SQL imports these
records without adding the spreadsheet's blank rows or aggregate row.

## API and checks

- `GET /api/meetings`: meeting history, saved attendee codes and recording status.
- `POST /api/meetings`: admin-only `{title, meeting_date: "YYYY-MM-DD"}`.
- `PATCH /api/meetings/{id}/attendance`: admin-only `{attendees: [member_code, ...]}`.

```powershell
node --test supabase/tests/attendance.test.mjs
npm --prefix frontend exec -- vitest run tests/attendance-ui.spec.jsx --root frontend --environment jsdom
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests/test_attendance.py -q
```
