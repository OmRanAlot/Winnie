-- Persist editable dashboard fields without replacing existing task/profile records.
begin;
alter table public.tasks
    add column if not exists notes text not null default '' check (length(notes) <= 10000),
    add column if not exists start_date date,
    add column if not exists due_time time,
    add column if not exists completed_at timestamptz;
alter table public.tasks add constraint tasks_start_before_due
    check (start_date is null or due_date is null or start_date <= due_date);

-- Historical completed tasks keep unknown completion times rather than invented dates.
create function public.track_task_completion() returns trigger
language plpgsql set search_path = '' as $$
begin
    if new.status <> 'done' then new.completed_at := null;
    elsif tg_op = 'INSERT' then new.completed_at := now();
    elsif old.status <> 'done' then new.completed_at := now();
    else new.completed_at := old.completed_at;
    end if;
    return new;
end;
$$;
revoke all on function public.track_task_completion() from public, anon, authenticated;
create trigger track_task_completion before insert or update on public.tasks
for each row execute function public.track_task_completion();

alter table public.members
    add column if not exists previous_roles text[] not null default '{}',
    add column if not exists previous_roles_override boolean not null default false,
    add column if not exists previous_role_skills_manual text[] not null default '{}';

create function public.update_dashboard_member(member text, changes jsonb) returns jsonb
language plpgsql set search_path = '' as $$
declare result public.members;
begin
    if exists (select 1 from jsonb_object_keys(changes) k where k not in
        ('display_name','board_role','skills','previous_roles','previous_role_skills_manual')) then
        raise exception 'Unsupported profile field' using errcode = '22023';
    end if;
    update public.members set
        display_name = case when changes ? 'display_name' then changes->>'display_name' else display_name end,
        board_role = case when changes ? 'board_role' then changes->>'board_role' else board_role end,
        role_description = case when changes ? 'board_role' and board_role <> changes->>'board_role' then '' else role_description end,
        role_responsibilities = case when changes ? 'board_role' and board_role <> changes->>'board_role' then '{}'::text[] else role_responsibilities end,
        delegation_context_verified = case when changes ? 'board_role' and board_role <> changes->>'board_role' then false else delegation_context_verified end,
        skills = case when changes ? 'skills' then array(select jsonb_array_elements_text(changes->'skills')) else skills end,
        previous_roles = case when changes ? 'previous_roles' then array(select jsonb_array_elements_text(changes->'previous_roles')) else previous_roles end,
        previous_roles_override = previous_roles_override or changes ? 'previous_roles',
        previous_role_skills_manual = case when changes ? 'previous_role_skills_manual'
            then array(select jsonb_array_elements_text(changes->'previous_role_skills_manual')) else previous_role_skills_manual end
    where code = member returning * into result;
    if not found then raise exception 'Member not found' using errcode = 'P0002'; end if;
    update public.profiles set name = result.display_name, role = result.board_role,
        skills = case when changes ? 'skills' then result.skills else skills end
    where member_code = member;
    return to_jsonb(result);
end;
$$;
revoke all on function public.update_dashboard_member(text,jsonb) from public, anon, authenticated;
grant execute on function public.update_dashboard_member(text,jsonb) to service_role;

create table public.member_evaluations (
    member_code text primary key references public.members(code) on delete cascade,
    comments text not null default '' check (length(comments) <= 10000),
    reviewer_id uuid not null references public.profiles(id),
    updated_at timestamptz not null default now()
);
create table public.dashboard_task_drafts (
    profile_id uuid primary key references public.profiles(id) on delete cascade,
    form jsonb not null check (jsonb_typeof(form) = 'object'),
    updated_at timestamptz not null default now()
);
alter table public.member_evaluations enable row level security;
alter table public.dashboard_task_drafts enable row level security;
revoke all on public.member_evaluations, public.dashboard_task_drafts from public, anon, authenticated;
grant all on public.member_evaluations, public.dashboard_task_drafts to service_role;
notify pgrst, 'reload schema';
commit;
