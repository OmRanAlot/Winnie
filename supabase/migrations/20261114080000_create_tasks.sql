-- Task persistence for FastAPI. Access is server-only until member authentication is built.
create sequence public.task_code_sequence;

create table public.tasks (
    id uuid primary key default gen_random_uuid(),
    task_code text not null unique,
    title text not null check (length(trim(title)) between 1 and 200),
    description text not null default '' check (length(description) <= 10000),
    month_code text not null check (month_code ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    status text not null default 'todo'
        check (status in ('todo', 'in_progress', 'blocked', 'done')),
    stakeholder_codes text[] not null default '{}'
        check (cardinality(stakeholder_codes) <= 50),
    owner_code text check (owner_code ~ '^[A-Z][A-Z0-9_-]{0,49}$'),
    due_date date,
    event_tag text check (length(event_tag) <= 100),
    tags text[] not null default '{}' check (cardinality(tags) <= 50),
    source text not null default 'manual'
        check (source in ('manual', 'meeting', 'sheet', 'doc', 'discord')),
    source_reference text check (length(source_reference) <= 2000),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create function public.set_task_fields() returns trigger
language plpgsql set search_path = '' as $$
begin
    if tg_op = 'INSERT' then
        new.task_code := 'WIN-' || replace(new.month_code, '-', '') || '-' ||
            nextval('public.task_code_sequence')::text;
    else
        if new.task_code <> old.task_code or new.month_code <> old.month_code then
            raise exception 'Task code and month code are immutable';
        end if;
        new.created_at := old.created_at;
    end if;
    if exists (
        select 1 from unnest(new.stakeholder_codes) as code
        where code is null or code !~ '^[A-Z][A-Z0-9_-]{0,49}$'
    ) then
        raise exception 'Invalid stakeholder code';
    end if;
    new.updated_at := now();
    return new;
end;
$$;

create trigger task_fields before insert or update on public.tasks
for each row execute function public.set_task_fields();

create index tasks_month_status_idx on public.tasks (month_code, status);
create index tasks_created_idx on public.tasks (created_at desc, id);
create index tasks_due_date_idx on public.tasks (due_date) where status <> 'done';
create index tasks_stakeholders_idx on public.tasks using gin (stakeholder_codes);

alter table public.tasks enable row level security;
revoke all on public.tasks from anon, authenticated;
revoke all on sequence public.task_code_sequence from anon, authenticated;
revoke execute on function public.set_task_fields() from public;
grant all on public.tasks to service_role;
grant usage, select on sequence public.task_code_sequence to service_role;
