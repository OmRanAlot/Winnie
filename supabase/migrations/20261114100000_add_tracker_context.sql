-- Apply AFTER 20261114080000_create_tasks.sql. Existing rows and task codes are preserved.
begin;

alter table public.tasks
    add column semester_code text
        check (semester_code ~ '^(spring|summer|fall|winter)-[0-9]{4}$'),
    add column project_name text check (length(project_name) <= 200),
    add column category text check (length(category) <= 200),
    add column priority text not null default 'normal'
        check (priority in ('low', 'normal', 'high')),
    add column assignee_text text not null default '' check (length(assignee_text) <= 2000),
    add column deadline_text text not null default '' check (length(deadline_text) <= 200),
    add column source_spreadsheet_id text
        check (source_spreadsheet_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$'),
    add column source_task_id text
        check (source_task_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$'),
    add column source_tab_id text
        check (source_tab_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$'),
    add column source_tab_name text check (length(source_tab_name) <= 200),
    add column snapshot_month text
        check (snapshot_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    add constraint tasks_source_identity_check
        check (source_task_id is null or source_spreadsheet_id is not null);

-- A task keeps this identity when a tab is renamed OLD, copied, or sorted.
-- Duplicated tabs retain their IDs; a genuinely new task needs a new ID.
create unique index tasks_source_identity_idx
    on public.tasks (source_spreadsheet_id, source_task_id)
    where source_spreadsheet_id is not null and source_task_id is not null;
create index tasks_semester_idx on public.tasks (semester_code);

comment on column public.tasks.month_code is
    'Legacy immutable task-code grouping; for sheet tasks, the first imported snapshot month. Not a deadline.';
comment on column public.tasks.snapshot_month is
    'Month represented by the active tracker snapshot, separate from due_date; changes on later syncs.';
comment on column public.tasks.assignee_text is
    'Original assignment cell, preserved until names/emails are resolved to opted-in members.';
comment on column public.tasks.source_task_id is
    'Permanent Winnie Task ID from the sheet. Never derive this from row position, title, or deadline.';

notify pgrst, 'reload schema';
commit;
