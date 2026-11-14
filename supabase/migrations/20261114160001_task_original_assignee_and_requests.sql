-- Apply only this migration to the current UUID task store, after roster/profiles.
begin;

alter table public.tasks add column original_assignee_code text
    references public.members(code) on delete restrict;

-- First-known baseline only. Never guess for multi-person or unknown aliases.
update public.tasks t set original_assignee_code = coalesce(
    t.owner_code,
    (select a.member_code from public.member_aliases a
     where a.semester_code = t.semester_code
       and lower(trim(a.alias)) = lower(trim(t.assignee_text)))
);
comment on column public.tasks.original_assignee_code is
    'First known individual assignee, preserved on reassignment. Existing rows use the current owner or exact semester alias; ambiguous history remains NULL.';

create function public.preserve_original_assignee() returns trigger
language plpgsql set search_path = '' as $$
begin
    if tg_op = 'UPDATE' then
        if new.original_assignee_code is distinct from old.original_assignee_code then
            raise exception 'Original assignee cannot be changed';
        end if;
        if old.original_assignee_code is not null or old.owner_code is not null
           or trim(old.assignee_text) <> '' then
            return new;
        end if;
    end if;
    new.original_assignee_code := coalesce(new.original_assignee_code, new.owner_code,
        (select a.member_code from public.member_aliases a
         where a.semester_code = new.semester_code
           and lower(trim(a.alias)) = lower(trim(new.assignee_text))));
    return new;
end;
$$;
revoke all on function public.preserve_original_assignee() from public, anon, authenticated;
create trigger tasks_preserve_original_assignee before insert or update on public.tasks
for each row execute function public.preserve_original_assignee();

create table public.task_reassignment_requests (
    id uuid primary key default gen_random_uuid(),
    task_id uuid not null references public.tasks(id) on delete restrict,
    requester_code text not null references public.members(code) on delete restrict,
    proposed_assignee_code text not null references public.members(code) on delete restrict,
    reason text not null default '' check (length(reason) <= 10000),
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    previous_owner_code text,
    previous_assignee_text text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    reviewed_by_profile_id uuid references public.profiles(id) on delete restrict,
    reviewed_at timestamptz,
    review_note text not null default '' check (length(review_note) <= 10000),
    check (
        (status = 'pending' and reviewed_by_profile_id is null and reviewed_at is null)
        or (status in ('approved', 'rejected') and reviewed_by_profile_id is not null and reviewed_at is not null)
    )
);
create unique index task_reassignment_one_pending_per_member
    on public.task_reassignment_requests (task_id, requester_code) where status = 'pending';
create index task_reassignment_pending_idx
    on public.task_reassignment_requests (created_at) where status = 'pending';
create index task_reassignment_task_idx on public.task_reassignment_requests (task_id, created_at);

create function public.can_review_task_requests() returns boolean
language sql stable security definer set search_path = '' as $$
    select exists (
        select 1 from public.profiles p left join public.members m on m.code = p.member_code
        where p.id = auth.uid() and (p.is_admin or
            (m.active and lower(trim(m.board_role)) in ('president', 'vice president')))
    );
$$;
revoke all on function public.can_review_task_requests() from public, anon;
grant execute on function public.can_review_task_requests() to authenticated, service_role;

create function public.guard_task_reassignment_request() returns trigger
language plpgsql set search_path = '' as $$
declare
    task_row public.tasks%rowtype;
    proposed_name text;
begin
    if tg_op = 'INSERT' then
        if new.status <> 'pending' then raise exception 'New requests must be pending'; end if;
        select * into strict task_row from public.tasks where id = new.task_id for update;
        if task_row.status = 'done' then raise exception 'Completed tasks cannot be reassigned'; end if;
        if not exists (select 1 from public.members where code = new.requester_code and active) then
            raise exception 'Requester must be an active member';
        end if;
        if not exists (select 1 from public.members where code = new.proposed_assignee_code and active) then
            raise exception 'Proposed assignee must be an active member';
        end if;
        if new.proposed_assignee_code = task_row.owner_code then
            raise exception 'Proposed assignee already owns the task';
        end if;
        new.previous_owner_code := task_row.owner_code;
        new.previous_assignee_text := task_row.assignee_text;
        new.created_at := now();
    else
        if old.status <> 'pending' then raise exception 'Request has already been reviewed'; end if;
        if row(new.task_id, new.requester_code, new.proposed_assignee_code, new.reason,
               new.previous_owner_code, new.previous_assignee_text)
           is distinct from row(old.task_id, old.requester_code, old.proposed_assignee_code, old.reason,
               old.previous_owner_code, old.previous_assignee_text) then
            raise exception 'Submitted request details cannot be changed';
        end if;
        new.created_at := old.created_at;
        if new.status in ('approved', 'rejected') then
            if not exists (
                select 1 from public.profiles p left join public.members m on m.code = p.member_code
                where p.id = new.reviewed_by_profile_id and (p.is_admin or
                    (m.active and lower(trim(m.board_role)) in ('president', 'vice president')))
            ) then raise exception 'Only the president, VP, or an admin can review requests'; end if;
            new.reviewed_at := now();
        end if;
        if new.status = 'approved' then
            select * into strict task_row from public.tasks where id = new.task_id for update;
            if task_row.status = 'done' then raise exception 'Completed tasks cannot be reassigned'; end if;
            if row(task_row.owner_code, task_row.assignee_text)
               is distinct from row(old.previous_owner_code, old.previous_assignee_text) then
                raise exception 'Task assignment changed; reject this request and submit a new one';
            end if;
            select display_name into proposed_name from public.members
                where code = new.proposed_assignee_code and active;
            if proposed_name is null then raise exception 'Proposed assignee must be active'; end if;
            update public.tasks set owner_code = new.proposed_assignee_code,
                assignee_text = proposed_name where id = new.task_id;
        end if;
    end if;
    new.updated_at := now();
    return new;
end;
$$;
revoke all on function public.guard_task_reassignment_request() from public, anon, authenticated;
create trigger task_reassignment_guard before insert or update on public.task_reassignment_requests
for each row execute function public.guard_task_reassignment_request();

alter table public.task_reassignment_requests enable row level security;
revoke all on public.task_reassignment_requests from public, anon, authenticated;
grant all on public.task_reassignment_requests to service_role;
grant select on public.task_reassignment_requests to authenticated;
create policy task_reassignment_read on public.task_reassignment_requests
for select to authenticated using (
    public.can_review_task_requests() or requester_code =
        (select member_code from public.profiles where id = (select auth.uid()))
);

-- These functions derive identity from the session, never from browser-supplied member codes.
create function public.submit_task_reassignment(p_task_id uuid, p_proposed_assignee_code text,
    p_reason text default '') returns public.task_reassignment_requests
language plpgsql security definer set search_path = '' as $$
declare
    requester text;
    result public.task_reassignment_requests;
begin
    select m.code into requester from public.profiles p join public.members m on m.code = p.member_code
        where p.id = auth.uid() and m.active;
    if requester is null then raise exception 'An authenticated active member is required'; end if;
    insert into public.task_reassignment_requests (task_id, requester_code, proposed_assignee_code, reason)
        values (p_task_id, requester, p_proposed_assignee_code, p_reason) returning * into result;
    return result;
end;
$$;
create function public.review_task_reassignment(p_request_id uuid, p_decision text,
    p_review_note text default '') returns public.task_reassignment_requests
language plpgsql security definer set search_path = '' as $$
declare
    result public.task_reassignment_requests;
begin
    if not public.can_review_task_requests() then
        raise exception 'Only the president, VP, or an admin can review requests';
    end if;
    if p_decision is null or p_decision not in ('approved', 'rejected') then
        raise exception 'Decision must be approved or rejected';
    end if;
    update public.task_reassignment_requests set status = p_decision,
        reviewed_by_profile_id = auth.uid(), review_note = p_review_note
        where id = p_request_id and status = 'pending' returning * into result;
    if not found then raise exception 'Pending request not found'; end if;
    return result;
end;
$$;
revoke all on function public.submit_task_reassignment(uuid, text, text) from public, anon;
revoke all on function public.review_task_reassignment(uuid, text, text) from public, anon;
grant execute on function public.submit_task_reassignment(uuid, text, text) to authenticated;
grant execute on function public.review_task_reassignment(uuid, text, text) to authenticated;

create view public.pending_task_requests with (security_invoker = true) as
select * from public.task_reassignment_requests where status = 'pending';
revoke all on public.pending_task_requests from public, anon;
grant select on public.pending_task_requests to authenticated, service_role;
comment on table public.task_reassignment_requests is
    'Member-proposed reassignments for president/VP/admin review. Approval atomically changes task owner; rejection preserves assignment. No external notifications are sent.';

notify pgrst, 'reload schema';
commit;
