-- Add meeting provenance to the canonical UUID task store. Existing UUIDs and codes stay intact.
begin;

create table if not exists public.meetings (
    id bigint generated always as identity primary key,
    held_at timestamptz not null,
    title text,
    transcript text,
    recording_id text unique
);
alter table public.meetings add column if not exists summary text;
alter table public.meetings enable row level security;
revoke all on public.meetings from anon, authenticated;
grant all on public.meetings to service_role;
grant usage, select on sequence public.meetings_id_seq to service_role;

alter table public.tasks
    add column if not exists source_meeting_id bigint references public.meetings(id) on delete set null,
    add column if not exists seat_text text,
    add column if not exists rationale text,
    add column if not exists deadline_at timestamptz,
    add column if not exists needs_review boolean not null default false,
    add column if not exists raw_json jsonb,
    add column if not exists legacy_task_id bigint unique;
create index if not exists tasks_source_meeting_idx on public.tasks(source_meeting_id);

create table if not exists public.task_dependencies (
    task_id uuid not null references public.tasks(id) on delete cascade,
    depends_on_id uuid not null references public.tasks(id) on delete cascade,
    primary key (task_id, depends_on_id),
    check (task_id <> depends_on_id)
);
create index if not exists task_dependencies_parent_idx on public.task_dependencies(depends_on_id);
alter table public.task_dependencies enable row level security;
revoke all on public.task_dependencies from anon, authenticated;
grant all on public.task_dependencies to service_role;

-- Copy, never delete, legacy records. Keep a mapping for links and operator reconciliation.
-- No name-based membership is inferred; verified member mappings remain authoritative.
do $copy$
begin
    if to_regclass('winnie_legacy.tasks') is not null then
        insert into public.tasks (
            legacy_task_id, title, description, month_code, status, source,
            source_reference, source_meeting_id, seat_text, assignee_text,
            rationale, deadline_text, due_date, deadline_at, needs_review, raw_json,
            semester_code, created_at, updated_at
        )
        select t.id, t.title, coalesce(t.description, ''),
            to_char(coalesce(m.held_at, t.created_at) at time zone 'America/New_York', 'YYYY-MM'),
            case when t.status = 'open' then 'todo' else t.status end, 'meeting',
            'legacy-task:' || t.id, t.source_meeting_id, s.name, coalesce(p.name, ''),
            t.rationale, coalesce(t.deadline_raw, ''),
            (t.deadline_at at time zone 'America/New_York')::date, t.deadline_at,
            t.needs_review, t.raw_json,
            case
                when extract(month from coalesce(m.held_at, t.created_at) at time zone 'America/New_York') <= 5 then 'spring-'
                when extract(month from coalesce(m.held_at, t.created_at) at time zone 'America/New_York') <= 8 then 'summer-'
                else 'fall-'
            end || to_char(coalesce(m.held_at, t.created_at) at time zone 'America/New_York', 'YYYY'),
            t.created_at, t.updated_at
        from winnie_legacy.tasks t
        left join public.meetings m on m.id = t.source_meeting_id
        left join public.seats s on s.id = t.seat_id
        left join public.people p on p.id = t.assignee_id
        where not exists (select 1 from public.tasks current where current.legacy_task_id = t.id);

        insert into public.task_dependencies(task_id, depends_on_id)
        select child.id, parent.id from winnie_legacy.task_dependencies e
        join public.tasks child on child.legacy_task_id = e.task_id
        join public.tasks parent on parent.legacy_task_id = e.depends_on_id
        on conflict do nothing;
    end if;
end;
$copy$;

notify pgrst, 'reload schema';
commit;
