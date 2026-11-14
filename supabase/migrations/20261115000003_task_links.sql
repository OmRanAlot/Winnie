-- Additive. Links tasks to meetings (LLM-only fields live here) and task dependencies. Re-runnable.
create table if not exists public.task_meeting_links (
    task_id      uuid   not null references public.tasks (id) on delete cascade,
    meeting_id   bigint not null references public.meetings (id) on delete cascade,
    segment_id   bigint references public.transcript_segments (id) on delete set null,
    rationale    text,
    needs_review boolean not null default false,
    deadline_raw text,
    raw_json     jsonb,
    primary key (task_id, meeting_id)
);
create index if not exists task_meeting_links_meeting_id_idx
    on public.task_meeting_links (meeting_id);
create index if not exists task_meeting_links_segment_id_idx
    on public.task_meeting_links (segment_id);

-- "task_id waits on depends_on_id".
create table if not exists public.task_dependencies (
    task_id       uuid not null references public.tasks (id) on delete cascade,
    depends_on_id uuid not null references public.tasks (id) on delete cascade,
    primary key (task_id, depends_on_id),
    check (task_id <> depends_on_id)
);
create index if not exists task_dependencies_depends_on_id_idx
    on public.task_dependencies (depends_on_id);

alter table public.task_meeting_links enable row level security;
alter table public.task_dependencies  enable row level security;

-- Defense in depth on Supabase: no anon/authenticated access to the new tables (the backend uses
-- the service-role key). Guarded so it also runs on plain Postgres.
do $$
declare t text;
begin
    foreach t in array array['members', 'meetings', 'meeting_attendees', 'transcript_segments',
                             'task_meeting_links', 'task_dependencies'] loop
        if exists (select 1 from pg_roles where rolname = 'anon') then
            execute format('revoke all on public.%I from anon, authenticated', t);
        end if;
        if exists (select 1 from pg_roles where rolname = 'service_role') then
            execute format('grant all on public.%I to service_role', t);
        end if;
    end loop;
end $$;
