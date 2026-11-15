-- Historical bootstrap: skip on databases already using the canonical UUID schema.
-- Numeric tasks created here are preserved and upgraded by the following migrations.
do $bootstrap$
begin
    if to_regclass('public.tasks') is not null then
        return;
    end if;
    execute $legacy$
-- Winnie task store: seats, people, meetings, tasks and task dependencies.
-- Apply with `supabase db push` (from the repo root) or paste into the Supabase SQL editor.
-- The backend talks to these tables with the service-role key (bypasses RLS). RLS is on with no
-- policies, so the anon/public key can read or write nothing until policies are added.

create table public.seats (
    id   bigint generated always as identity primary key,
    name text not null unique
);

create table public.people (
    id      bigint generated always as identity primary key,
    name    text   not null,
    aliases text[] not null default '{}'
);
-- One person per spelling, ignoring case (repository.get_or_create_person relies on this).
create unique index people_name_lower_key on public.people (lower(name));

create table public.meetings (
    id           bigint generated always as identity primary key,
    held_at      timestamptz not null,
    title        text,
    transcript   text,
    -- The browser recording this meeting came from. Unique so retrying task assignment for the
    -- same recording reuses the meeting instead of duplicating every task.
    recording_id text unique
);

create table public.tasks (
    id                bigint generated always as identity primary key,
    title             text        not null,
    description       text,
    seat_id           bigint      references public.seats (id) on delete set null,
    assignee_id       bigint      references public.people (id) on delete set null,
    rationale         text,
    deadline_raw      text,
    deadline_at       timestamptz,
    needs_review      boolean     not null default false,
    status            text        not null default 'open'
                                  check (status in ('open', 'done', 'blocked')),
    source_meeting_id bigint      references public.meetings (id) on delete set null,
    raw_json          jsonb,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index tasks_assignee_id_idx       on public.tasks (assignee_id);
create index tasks_seat_id_idx           on public.tasks (seat_id);
create index tasks_status_idx            on public.tasks (status);
create index tasks_deadline_at_idx       on public.tasks (deadline_at);
create index tasks_source_meeting_id_idx on public.tasks (source_meeting_id);

-- "task_id waits on depends_on_id". Longer cycles are rejected in app/repository.py.
create table public.task_dependencies (
    task_id       bigint not null references public.tasks (id) on delete cascade,
    depends_on_id bigint not null references public.tasks (id) on delete cascade,
    primary key (task_id, depends_on_id),
    check (task_id <> depends_on_id)
);
create index task_dependencies_depends_on_id_idx on public.task_dependencies (depends_on_id);

-- Keep tasks.updated_at current on every update.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger tasks_set_updated_at
before update on public.tasks
for each row execute function public.set_updated_at();

alter table public.seats             enable row level security;
alter table public.people            enable row level security;
alter table public.meetings          enable row level security;
alter table public.tasks             enable row level security;
alter table public.task_dependencies enable row level security;

$legacy$;
end;
$bootstrap$;
