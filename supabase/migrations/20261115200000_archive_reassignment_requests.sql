-- Resolved task reassignment requests can be archived by an administrator.
begin;

alter table public.task_reassignment_requests
add column archived_at timestamptz,
add column archived_by_profile_id uuid references public.profiles (id) on delete restrict,
add constraint task_reassignment_archive_state check (
    archived_at is null
    or status in (
        'approved',
        'rejected',
        'declined'
    )
);

-- Preserve the existing review lock while allowing an admin to change only archive metadata.
create or replace function public.guard_task_reassignment_request() returns trigger
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
        if old.status <> 'pending' then
            if new.status = old.status and new.archived_at is distinct from old.archived_at
               and row(new.task_id, new.requester_code, new.proposed_assignee_code, new.reason,
                   new.previous_owner_code, new.previous_assignee_text, new.recipient_decision,
                   new.responded_by_profile_id, new.responded_at, new.reviewed_by_profile_id,
                   new.reviewed_at, new.review_note, new.request_no, new.archived_by_profile_id)
                   is not distinct from row(old.task_id, old.requester_code, old.proposed_assignee_code,
                   old.reason, old.previous_owner_code, old.previous_assignee_text,
                   old.recipient_decision, old.responded_by_profile_id, old.responded_at,
                   old.reviewed_by_profile_id, old.reviewed_at, old.review_note, old.request_no,
                   old.archived_by_profile_id)
               and exists (select 1 from public.profiles where id = auth.uid() and is_admin) then
                new.archived_by_profile_id := case when new.archived_at is null then null else auth.uid() end;
                new.updated_at := now();
                return new;
            end if;
            raise exception 'Request has already been reviewed';
        end if;
        if row(new.task_id, new.requester_code, new.proposed_assignee_code, new.reason,
               new.previous_owner_code, new.previous_assignee_text)
           is distinct from row(old.task_id, old.requester_code, old.proposed_assignee_code,
               old.reason, old.previous_owner_code, old.previous_assignee_text) then
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

drop policy task_reassignment_read on public.task_reassignment_requests;

create policy task_reassignment_read on public.task_reassignment_requests for
select to authenticated using (
        exists (
            select 1
            from public.profiles
            where
                id = auth.uid ()
                and is_admin
        )
        or (
            archived_at is null
            and (
                public.can_review_task_requests ()
                or requester_code = public.current_board_member_code ()
                or proposed_assignee_code = public.current_board_member_code ()
            )
        )
    );

create function public.archive_task_reassignment(p_request_id uuid, p_archive boolean default true)
returns public.task_reassignment_requests
language plpgsql security definer set search_path = '' as $$
declare
    saved public.task_reassignment_requests;
begin
    if not exists (select 1 from public.profiles where id = auth.uid() and is_admin) then
        raise exception 'Only admins can archive task reassignment requests';
    end if;
    if p_archive is null then raise exception 'Archive choice is required'; end if;
    select * into saved from public.task_reassignment_requests
     where id = p_request_id and status in ('approved', 'rejected', 'declined') for update;
    if not found then raise exception 'Only resolved requests can be archived'; end if;
    if (saved.archived_at is not null) = p_archive then return saved; end if;
    update public.task_reassignment_requests
       set archived_at = case when p_archive then now() else null end
     where id = p_request_id
     returning * into saved;
    return saved;
end;
$$;

revoke all on function public.archive_task_reassignment (uuid, boolean)
from public, anon;

grant
execute on function public.archive_task_reassignment (uuid, boolean) to authenticated;

notify pgrst, 'reload schema';

commit;