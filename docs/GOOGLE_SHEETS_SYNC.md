# Live Google Sheets synchronization

For the deployed automatic runner, see [AUTOMATION.md](AUTOMATION.md). Only configured sources with auto_apply=true are written, and conflicts still require review.

Winnie can read a private Google tracker directly, preview its changes, and apply
them to Supabase. A separate worker can repeat the sync every five minutes. The
spreadsheet stays private; this feature does not write back to Google Sheets.

The selected source is the **October 2026** tab in the
[Fall 2026 task tracker](https://docs.google.com/spreadsheets/d/1RtpILfXjEWj926Z57mOfEAoWNGUY2Cgj_86CSeRiX-U/edit#gid=1107311783).
It already has a **Winnie Task ID** column. The local backend configuration has
been set to this source, with automatic writes off until the first review.

## Cost

Google documents standard Sheets API use as available at no additional cost.
This worker normally reads the configured workbook a few times per five-minute
cycle, far below the published standard per-minute quotas for a single tracker.
Do not request paid quota increases for this setup. API pricing/quota policy can
change; see [Google's current usage limits](https://developers.google.com/workspace/sheets/api/limits).
Running/hosting the Winnie backend is separate from Sheets API usage.

## One-time Google setup

The Google Drive connection used inside a Codex chat does not give a running
Winnie server credentials. Configure the backend's own Google identity:

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or
   select a project, for example **Winnie**.
2. Open **APIs & Services → Library**, find **Google Sheets API**, and enable it.
3. Open **IAM & Admin → Service Accounts → Create service account**. Name it
   `winnie-sheets-reader`. The optional project-role and user-access steps can be
   skipped; this account does not need a project-wide Editor/Owner role.
4. Open the created account and copy its email address (ending in
   `iam.gserviceaccount.com`). Open the tracker in Google Sheets, click **Share**,
   and give that email **Viewer** access. Keep general access restricted.
5. In the service account's **Keys** tab, choose **Add key → Create new key → JSON**.
   Save the downloaded file privately, outside the repository. If your school
   blocks service-account key creation or external sharing, ask its administrator
   about an approved Google identity; do not make the tracker public to bypass it.
6. Add the file's full path to the repository-root `.env`, for example:

   ```dotenv
   WINNIE_SHEETS_CREDENTIALS_FILE=C:/Users/shara/.config/winnie/google-sheets-service-account.json
   ```

Do not paste key contents into chat, commit the JSON, or put credentials in
`frontend/.env`. Winnie requests the read-only Sheets OAuth scope. On a hosted
Google environment, Application Default Credentials with workbook access may be
used instead; leave `WINNIE_SHEETS_CREDENTIALS_FILE` unset in that case.

Google references: [create credentials and share with service accounts](https://developers.google.com/workspace/guides/create-credentials),
[read-only scope](https://developers.google.com/workspace/sheets/api/scopes).

## One-time database setup

Apply only the new sync migration after your existing migrations:

[`20261115130000_google_sheet_sync.sql`](../supabase/migrations/20261115130000_google_sheet_sync.sql)

It adds private source-baseline and successful-sync-history tables plus an atomic
server-only apply function. It does not import tasks or send messages on its own.
The backend uses its existing Supabase secret. Browser users still need to sign
in as administrators to preview or apply a sync.

## Configure the selected tracker

In the repository-root `.env` (not `frontend/.env`), keep this JSON on **one line**:

```dotenv
WINNIE_SHEET_SYNC_SOURCES=[{"key":"fall-board","spreadsheet_id":"1RtpILfXjEWj926Z57mOfEAoWNGUY2Cgj_86CSeRiX-U","semester_code":"fall-2026","tab_name":"October 2026","auto_apply":false}]
WINNIE_SHEET_SYNC_INTERVAL_SECONDS=300
```

Restart FastAPI after changing `.env`. Stop and restart an already-running sync
worker too: it loads configuration at startup. If `backend/.env` also sets the
same variables, its values override the repository-root file; update/remove the
duplicate entries. Hosted deployments use the same variable names in their
server environment/secrets configuration.

## First sync: review before enabling automatic writes

1. Start the backend and frontend normally.
2. Sign in as an admin. Open **Admin Settings → Google Sheets Sync**.
3. Select `fall-board` and click **Build Preview**. This reads Google and Supabase
   without writing either source or database.
4. Review new/updated task fields. If existing CSV-imported tasks differ from the
   sheet, choose **Keep Winnie** or **Use Sheets** for each conflict, then click
   **Build Preview** again. No prior live baseline means Winnie cannot safely
   assume which side's differing value is newer.
5. Click **Apply Reviewed Changes**. The app re-reads both sources and checks the
   preview again. If anything changed, build a fresh preview instead of forcing it.

An entire batch is one database transaction: a conflict or stale revision rolls
back all its writes. The last successful apply appears on the sync screen. A
network timeout after apply can leave the outcome unknown; build a new preview
or check last-applied history before retrying.

## Turn on automatic synchronization

After a successful reviewed first sync, change `"auto_apply":false` to
`"auto_apply":true` in the source configuration and restart the backend. Then,
from `backend/`, run this in a **separate terminal**:

```powershell
.\.venv\Scripts\python.exe -m app.cli.sync_sheets --watch --apply
```

Keep that process running alongside FastAPI. It polls every 300 seconds. A process
manager can run the same command for deployment; the API does not start a hidden
worker. For one write-enabled cycle, omit `--watch`. To preview once without any
writes, omit both `--watch` and `--apply`:

```powershell
.\.venv\Scripts\python.exe -m app.cli.sync_sheets
```

Both the command's `--apply` flag and the source's `auto_apply:true` are needed for
automatic writes. Unresolved conflicts skip the entire tracker. Check worker
output for `conflict`/`failed`, then use the admin preview to investigate; worker
logs do not print cell values, contacts or credentials. Last-applied time shows
successful transactions, not proof that a worker is currently running.

## Change the active tab each month

For example, switching from October to November:

1. In Google Sheets, duplicate the active tab and name the new tab **November 2026**.
2. **Keep every existing Winnie Task ID unchanged.** Sorting rows, editing titles,
   or copying a task into the next month must not create a new ID. Give genuinely
   new tasks new unused IDs, for example `FALL26-128`; never reuse an old ID.
3. Rename the old tab **OLD October 2026** when it becomes an archive.
4. Stop the sync worker while changing the active source.
5. In `.env`, change only `"tab_name":"October 2026"` to
   `"tab_name":"November 2026"`. Keep `key`, `spreadsheet_id`, and
   `semester_code` unchanged. Temporarily use `"auto_apply":false` for review.
6. Restart FastAPI, build a preview for the new tab, and apply it. Existing IDs
   update the same Supabase tasks; new IDs add tasks. No old tasks are deleted.
7. Restore `"auto_apply":true`, restart FastAPI and the worker, and confirm a
   successful cycle.

**Do not configure old and new monthly copies as two active sources.** Configure
one active tab per tracker. Winnie refuses `OLD` tabs and refuses to overwrite a
later stored monthly snapshot with an earlier one. If the tab is merely renamed,
update `tab_name` to the exact new name. An advanced alternative is `tab_id` with
the numeric `gid` from the tab URL; use either `tab_name` or `tab_id`, never both.

## Change semesters or add a separate tracker

For a new semester workbook, use its new `spreadsheet_id`, the new
`semester_code` (for example `spring-2027`), its active tab, and preferably a new
source `key` (for example `spring-board`). Old semester records remain in Supabase.
Do not relabel an already-imported workbook with a different source ID.

For a separate GirlHacks/category tracker, add another object to the JSON list
with a unique key and `project_name`. For a non-monthly tab also set
`initial_month`, such as `2026-11`. Task IDs must be unique across active task lists
inside the same workbook, including separate project tabs.

## Merge rules and supported layout

- Task identity is `(spreadsheet_id, Winnie Task ID)`, never the row position/title.
- Sheets may update task title, imported description/notes, status, priority,
  assignee text, deadline, event/category/project and source-snapshot metadata.
- If a sheet cell has not changed since the previous sync, a local Winnie change
  is preserved. If both sides changed that field differently, admin review is
  required. Keeping Winnie acknowledges the new sheet value as the baseline so
  the same conflict does not repeat every cycle.
- Explicit local `owner_code` reassignment, personal task `notes`, and other
  Winnie-only fields are never overwritten. Imported sheet **Notes** maps to the
  task description, separate from personal notes.
- Rows removed from the sheet keep their tasks in Winnie. Deleting a task only in
  Winnie while leaving its source row may recreate it on the next sync.
- Keep **File → Settings → Locale: United States**. Deadlines use `M/D/YYYY` or
  `YYYY-MM-DD`; ambiguous non-US date formatting is rejected. Time zone remains
  America/New_York.
- Required headers are Event (or Category), Task Name, Status, Priority, Assignee,
  Deadline, Notes, and Winnie Task ID. Missing/duplicate IDs, unsupported status
  labels or malformed dates block sync with a visible error. Existing CSV/TSV
  tracker validation and archived-snapshot rules are reused.
- Reads are bounded to 10,000 rows and 52 columns per source. Larger trackers
  require splitting/configuration changes rather than silently truncating tasks.

## Checks

```powershell
node --test supabase/tests/sheet-sync.test.mjs
npm --prefix frontend exec -- vitest run tests/sheet-sync-ui.spec.jsx --root frontend --environment jsdom
```

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sheet_sync.py tests/test_tracker_sync.py tests/test_tracker_import.py -q
```
