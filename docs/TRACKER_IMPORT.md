# Semester tracker imports

Winnie's trackers have one spreadsheet per semester and monthly copies of the full
task list. A tab named `OLD March 2026` is a historical snapshot, not a list of
completed tasks. GirlHacks is a separate project tracker whose deadlines can span
semesters.

## What is implemented

- A second database migration adds semester, project, priority, original assignee
  and deadline text, source identity, and snapshot fields without deleting existing tasks.
- The task API accepts those fields and supports `GET /api/tasks?semester_code=spring-2026`.
- A local CSV/TSV preview maps both the monthly and GirlHacks layouts. It never
  accesses Google or Supabase and never writes tasks.
- Preview reports flag missing/duplicate permanent IDs, unknown statuses, invalid
  dates, and malformed rows. Optional JSON reports retain original cells for review.
- `app.import_tracker` compares valid rows against Supabase and previews insert,
  update, and unchanged counts. Saving requires the exact preview's confirmation hash.

Live Google Sheets access, writing IDs into sheets, archive
history storage, scheduled synchronization, and reminder sending are not implemented
yet. A private sheet can remain private when those are added.

## First: apply the new migration

In the Supabase project's SQL Editor, open a new query and paste **only**
`supabase/migrations/20261114100000_add_tracker_context.sql`, then Run once.
The original tasks migration must already have succeeded. Do not rerun that original
creation script. The new migration is transactional: a failure rolls back its changes.
It preserves existing task IDs, codes and rows, and keeps server-only access rules.

Restart FastAPI after updating the code. Existing manual task requests remain valid.
The new fields are optional for existing tasks; no semester is guessed for old records.

## What each field means

| Field | Meaning |
|---|---|
| `semester_code` | Source tracker semester, such as `spring-2026`; not inferred from deadlines |
| `project_name` | Project such as `GirlHacks 2026`, independent of source semester |
| `event_tag` | Event cell from the monthly tracker |
| `category` | Category cell from GirlHacks |
| `priority` | Low/Normal/High normalized to `low`/`normal`/`high` |
| `assignee_text` | Original cell, including multiple names/emails; no guessed person matching |
| `deadline_text` | Original deadline string, including `As needed` |
| `due_date` | Parsed US date, or null for no fixed deadline; preserve the source year |
| `source_spreadsheet_id` | Google spreadsheet ID, stable across monthly tabs |
| `source_task_id` | Permanent `Winnie Task ID` from the sheet |
| `source_tab_id` | Google tab's numeric gid, stored as text; survives a rename |
| `source_tab_name` | Display name, such as `April 2026` |
| `snapshot_month` | Month parsed from the tab name, not a task deadline |
| `month_code` | Existing immutable code grouping; first imported snapshot month, or explicitly supplied initial month for a non-monthly tracker |

For example, a Spring task can have snapshot month `2026-04` and a June deadline.
The two-digit date `04/20/26` is interpreted as April 20, 2026. Unrecognized date
text requires review; `As needed`, blank, `TBD`, and `N/A` preserve the text with no
fixed date. Such tasks cannot drive date-based reminders until given a deadline.

## Permanent IDs and monthly copies

Add one `Winnie Task ID` column to the active live tracker. Each distinct task needs
a unique value such as `SPR26-001`. Copy the value with the task when duplicating
tabs. Give a genuinely new task a new ID. Never recompute IDs from row numbers,
titles, assignments or deadlines. An ID generator/write-back step can be added later.

Within a spreadsheet, the pair `(source_spreadsheet_id, source_task_id)` uniquely
identifies a task in Supabase. The database has a unique index to prevent two rows
with the same pair. A future importer must look up this pair and update the existing
task, preserving `month_code`, rather than blindly inserting each monthly copy.
Task identity is not silently changed through the ordinary task PATCH API.

The supplied historical CSVs have no permanent IDs. They can be previewed, but are
not ready for a current-state sync. Matching by event/title is only a review aid;
it cannot safely establish identity for edited or repeated tasks. Do not bulk-import
March and April as separate task lists. A task absent from the active tab should not
be automatically deleted or marked complete.

Select one active tab per tracker. OLD tabs remain history and must not overwrite
current task state or initiate reminders. The preview classifies them but does not
store their history. Snapshot month alone is not enough to order edits within a month;
live sync will need a revision/timestamp and an explicit active-tab configuration.

## Run a preview

From the `backend/` terminal (the API can stay running in another terminal):

```powershell
uv run python -m app.preview_tracker "C:/path/to/April 2026.csv" --semester spring-2026 --spreadsheet-id spring-demo --tab "April 2026"
```

For an offline example, `spring-demo` is only a label. For a future live connection,
use the real Google spreadsheet ID. Preview does not authenticate with Google.
The tab's display name is supplied explicitly because a CSV has no workbook metadata.

For GirlHacks, supply a project and explicit initial month for its legacy task codes:

```powershell
uv run python -m app.preview_tracker "C:/path/to/GirlHacks.csv" --semester spring-2026 --spreadsheet-id spring-demo --tab GirlHacks --project "GirlHacks 2026" --initial-month 2026-11
```

The initial month does not assign a deadline or force GirlHacks into November.
For a non-monthly tab, `snapshot_month` stays null.

The terminal prints only counts and issue codes. `missing_winnie_task_id` means the
task needs a permanent ID before automatic updates are safe. `ready_for_current_sync`
means local validation passed, not that database insert/update decisions were made.
The preview does not compare against existing Supabase tasks.

Optionally append `--output data/imports/april-preview.json` to save a detailed private
report. Reports can contain member names/emails and task notes. Keep them under the
gitignored `data/` folder, never commit them, and don't use an existing report name.
The original CSV/TSV is never overwritten. This preview has no apply flag.

## Preview against Supabase, then save

After adding permanent IDs and applying both migrations, use `app.import_tracker`.
Unlike the offline preview, this command needs the backend's Supabase credentials
in the repository-root `.env`. It reads existing tasks by their source identity.
No new migration is needed for the import command itself.

Use the **real spreadsheet ID** from the URL between `/d/` and `/edit`. This does
not grant access to Google; the CSV is still the input. It establishes a permanent
identity that a later live Sheets connection can reuse. Do not save tasks with
`spring-demo` and later change the ID: that would describe a different source.

Run from `backend/`, substituting your file path and spreadsheet ID:

```powershell
.\.venv\Scripts\python.exe -m app.import_tracker "C:/path/to/April with IDs.csv" --semester spring-2026 --spreadsheet-id YOUR_SHEET_ID --tab "April 2026"
```

It prints `mode: database_preview`, `database_writes: 0`, a `plan_id`, counts for
insert/update/unchanged, and any status changes. To review all proposed data and
before/after changes, append `--output data/imports/supabase-plan.json` and open
that private JSON report in the IDE. Choose a new filename on subsequent runs.
Do not commit reports containing member details.

After reviewing, run the same command with `--apply --expect-plan THE_PLAN_ID`:

```powershell
.\.venv\Scripts\python.exe -m app.import_tracker "C:/path/to/April with IDs.csv" --semester spring-2026 --spreadsheet-id YOUR_SHEET_ID --tab "April 2026" --apply --expect-plan THE_PLAN_ID
```

The command rebuilds the plan before saving. If the input, relevant stored records,
or target database changed, it rejects the previous confirmation. Preview again.
After a successful import, previewing the same file should report all tasks as
unchanged. `GET /api/tasks?semester_code=spring-2026&limit=100` can verify stored tasks;
use pagination to see more than 100.

Existing task UUIDs, generated task codes, immutable `month_code`, member mappings,
and non-sheet tags are preserved. Sheet-owned fields (including status) follow the
explicitly reviewed import. The command rejects OLD tabs, invalid rows, and monthly
snapshots older than those already stored for this tracker. It does not delete tasks
absent from the file. It cannot detect an older export from within the same month;
review the diff and keep automatic recurring writes disabled until revision and
conflict rules are agreed.

Each save request is an individual database transaction. If a request fails, the
command stops and reports completed operations and attempted writes. Earlier writes
are not rolled back, and a timed-out request may already have committed. Run a fresh
preview before retrying: stored identities prevent reinserting the same tasks, and
updates check `updated_at` to avoid overwriting changes made after planning. A unique
index prevents concurrent inserts from duplicating a source task; a conflict stops
the run instead of silently overwriting it. No reminders are sent by this command.

The next milestone is live read access to the private Google Sheet, using the same
permanent IDs. Agree on who controls status when it changes in both Winnie and the
spreadsheet before enabling recurring writes.
