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
declare t public.tasks; proposed_name text;
begin
    if tg_op='INSERT' then
        if new.status<>'pending' or new.admin_decision<>'pending' or new.recipient_decision<>'pending'
          or new.reviewed_by_profile_id is not null or new.responded_by_profile_id is not null
          or new.reviewed_at is not null or new.responded_at is not null or new.handoff_completed_at is not null
          or new.archived_at is not null or new.archived_by_profile_id is not null then
            raise exception 'New requests must await admin review';
        end if;
        select * into strict t from public.tasks where id=new.task_id for update;
        if t.status='done' then raise exception 'Completed tasks cannot be reassigned'; end if;
        if not exists(select 1 from public.members where code=new.requester_code and active)
          or not exists(select 1 from public.members where code=new.proposed_assignee_code and active) then
            raise exception 'Requester and proposed assignee must be active';
        end if;
        if new.proposed_assignee_code=t.owner_code then raise exception 'Proposed assignee already owns the task'; end if;
        new.previous_owner_code:=t.owner_code; new.previous_assignee_text:=t.assignee_text;
        new.initiated_by_profile_id:=auth.uid(); new.created_at:=now();
    else
        if new.archived_at is distinct from old.archived_at then
            if old.status not in ('approved','rejected','declined')
              or row(new.status,new.task_id,new.requester_code,new.proposed_assignee_code,new.reason,
                new.previous_owner_code,new.previous_assignee_text,new.recipient_decision,
                new.responded_by_profile_id,new.responded_at,new.reviewed_by_profile_id,new.reviewed_at,
                new.review_note,new.request_no,new.initiated_by_profile_id,new.admin_decision,
                new.handoff_completed_at,new.legacy_recipient_response)
                is distinct from row(old.status,old.task_id,old.requester_code,old.proposed_assignee_code,
                old.reason,old.previous_owner_code,old.previous_assignee_text,old.recipient_decision,
                old.responded_by_profile_id,old.responded_at,old.reviewed_by_profile_id,old.reviewed_at,
                old.review_note,old.request_no,old.initiated_by_profile_id,old.admin_decision,
                old.handoff_completed_at,old.legacy_recipient_response)
              or not exists(select 1 from public.profiles where id=auth.uid() and is_admin) then
                raise exception 'Only admins can archive resolved requests';
            end if;
            new.archived_by_profile_id:=case when new.archived_at is null then null else auth.uid() end;
            new.updated_at:=now();
            return new;
        end if;
        if old.status<>'pending' then raise exception 'Request has already been reviewed'; end if;
        if row(new.task_id,new.requester_code,new.proposed_assignee_code,new.reason,new.previous_owner_code,
          new.previous_assignee_text,new.initiated_by_profile_id,new.legacy_recipient_response)
          is distinct from row(old.task_id,old.requester_code,old.proposed_assignee_code,old.reason,
          old.previous_owner_code,old.previous_assignee_text,old.initiated_by_profile_id,old.legacy_recipient_response) then
            raise exception 'Submitted request details cannot be changed';
        end if;
        new.created_at:=old.created_at;
        if new.admin_decision is distinct from old.admin_decision then
            if old.admin_decision<>'pending' or not public.can_review_task_requests()
              or new.reviewed_by_profile_id is distinct from auth.uid()
              or new.admin_decision not in ('approved','rejected') or new.recipient_decision<>'pending' then
                raise exception 'Only an admin can review a pending proposal';
            end if;
            new.reviewed_at:=now();
        elsif row(new.reviewed_by_profile_id,new.reviewed_at,new.review_note) is distinct from
          row(old.reviewed_by_profile_id,old.reviewed_at,old.review_note) then
            raise exception 'Administrator review is immutable';
        end if;
        if row(new.recipient_decision,new.responded_by_profile_id,new.responded_at) is distinct from
          row(old.recipient_decision,old.responded_by_profile_id,old.responded_at) then
            if old.admin_decision<>'approved' then raise exception 'Administrator approval is required before recipient consent'; end if;
            if old.recipient_decision<>'pending' or public.current_board_member_code() is distinct from old.proposed_assignee_code
              or new.responded_by_profile_id is distinct from auth.uid()
              or new.recipient_decision not in ('accepted','denied') then
                raise exception 'Only the proposed recipient can respond';
            end if;
            new.responded_at:=now();
        end if;
        if new.status is distinct from (case when new.admin_decision='rejected' then 'rejected'
          when new.recipient_decision='denied' then 'declined'
          when new.admin_decision='approved' and new.recipient_decision='accepted' then 'approved' else 'pending' end) then
            raise exception 'Invalid transfer stage';
        end if;
        if new.admin_decision='approved' and (old.admin_decision<>'approved' or new.status='approved') then
            select * into strict t from public.tasks where id=new.task_id for update;
            if t.status='done' then raise exception 'Completed tasks cannot be reassigned'; end if;
            if row(t.owner_code,t.assignee_text) is distinct from row(old.previous_owner_code,old.previous_assignee_text) then
                raise exception 'Task assignment changed; ask for a new request';
            end if;
        end if;
        if new.status='approved' then
            select display_name into proposed_name from public.members where code=new.proposed_assignee_code and active;
            if proposed_name is null then raise exception 'Proposed assignee must be active'; end if;
            if not exists(select 1 from public.profiles p join public.members m on m.code=p.member_code
              where p.id=new.reviewed_by_profile_id and m.active and m.contact_consent and p.password_setup_complete
              and (p.is_admin or lower(trim(m.board_role)) in ('president','vice president'))) then
                raise exception 'Administrator approval is no longer authorized';
            end if;
            update public.tasks set owner_code=new.proposed_assignee_code,assignee_text=proposed_name where id=new.task_id;
            new.handoff_completed_at:=now();
        end if;
    end if;
    new.updated_at:=now();
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
