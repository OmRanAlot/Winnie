-- Recipient consent is required before an administrator can transfer a task.
begin;
alter table public.task_reassignment_requests
    add column recipient_decision text not null default 'pending'
        check (recipient_decision in ('pending','accepted','denied')),
    add column responded_by_profile_id uuid references public.profiles(id) on delete restrict,
    add column responded_at timestamptz;
alter table public.task_reassignment_requests
    drop constraint task_reassignment_requests_status_check,
    drop constraint task_reassignment_requests_check,
    add constraint task_reassignment_requests_status_check
        check (status in ('pending','approved','rejected','declined')),
    add constraint task_reassignment_review_state check (
        (status in ('pending','declined') and reviewed_by_profile_id is null and reviewed_at is null)
        or (status in ('approved','rejected') and reviewed_by_profile_id is not null and reviewed_at is not null)
    ),
    add constraint task_reassignment_recipient_state check (
        (recipient_decision = 'pending' and responded_by_profile_id is null and responded_at is null)
        or (recipient_decision in ('accepted','denied') and responded_by_profile_id is not null and responded_at is not null)
    ),
    add constraint task_reassignment_decline_state check (
        (status = 'declined') = (recipient_decision = 'denied')
    );

create function public.guard_task_recipient_consent() returns trigger
language plpgsql set search_path = '' as $$
begin
    if tg_op = 'INSERT' then
        if new.recipient_decision <> 'pending' or new.responded_at is not null
           or new.responded_by_profile_id is not null then
            raise exception 'New requests must await recipient consent';
        end if;
    else
        if row(new.recipient_decision,new.responded_by_profile_id,new.responded_at)
           is distinct from row(old.recipient_decision,old.responded_by_profile_id,old.responded_at) then
            if old.status <> 'pending' or old.recipient_decision <> 'pending' then
                raise exception 'This request has already been answered or closed';
            end if;
            if public.current_board_member_code() is distinct from old.proposed_assignee_code
               or new.responded_by_profile_id is distinct from auth.uid() then
                raise exception 'Only the proposed recipient can respond';
            end if;
            if new.recipient_decision not in ('accepted','denied')
               or new.status <> (case when new.recipient_decision = 'denied' then 'declined' else 'pending' end) then
                raise exception 'Invalid recipient response';
            end if;
            new.responded_at := now();
        end if;
    end if;
    if new.status = 'approved' and new.recipient_decision <> 'accepted' then
        raise exception 'The proposed recipient must accept before administrator approval';
    end if;
    return new;
end;
$$;
revoke all on function public.guard_task_recipient_consent() from public, anon, authenticated;
create trigger task_reassignment_consent_guard before insert or update on public.task_reassignment_requests
for each row execute function public.guard_task_recipient_consent();

create function public.respond_task_reassignment(p_request_id uuid, p_decision text)
returns public.task_reassignment_requests
language plpgsql security definer set search_path = '' as $$
declare
    member text := public.current_board_member_code();
    request public.task_reassignment_requests;
    task public.tasks;
begin
    if member is null then raise exception 'A verified active member is required'; end if;
    if p_decision is null or p_decision not in ('accepted','denied') then
        raise exception 'Response must be accepted or denied';
    end if;
    select * into request from public.task_reassignment_requests where id = p_request_id for update;
    if not found or request.proposed_assignee_code <> member then
        raise exception 'Incoming request not found';
    end if;
    if request.status <> 'pending' or request.recipient_decision <> 'pending' then
        raise exception 'This request has already been answered or closed';
    end if;
    if p_decision = 'accepted' then
        select * into strict task from public.tasks where id = request.task_id for update;
        if task.status = 'done' then raise exception 'Completed tasks cannot be reassigned'; end if;
        if row(task.owner_code,task.assignee_text) is distinct from
           row(request.previous_owner_code,request.previous_assignee_text) then
            raise exception 'Task assignment changed; ask for a new request';
        end if;
    end if;
    update public.task_reassignment_requests set recipient_decision = p_decision,
        responded_by_profile_id = auth.uid(), responded_at = now(),
        status = case when p_decision = 'denied' then 'declined' else 'pending' end
        where id = p_request_id returning * into request;
    return request;
end;
$$;
revoke all on function public.respond_task_reassignment(uuid,text) from public, anon;
grant execute on function public.respond_task_reassignment(uuid,text) to authenticated;
drop policy task_reassignment_read on public.task_reassignment_requests;
create policy task_reassignment_read on public.task_reassignment_requests for select to authenticated using (
    public.can_review_task_requests() or requester_code = public.current_board_member_code()
    or proposed_assignee_code = public.current_board_member_code()
);
comment on table public.task_reassignment_requests is
    'Recipient accepts or declines a proposed transfer. Administrator approval after acceptance atomically transfers ownership. Decline preserves ownership.';
notify pgrst, 'reload schema';
commit;
