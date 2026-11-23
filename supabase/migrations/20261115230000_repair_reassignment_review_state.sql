-- Repair a partially installed admin-first reassignment workflow atomically.
-- Keep authorization, review metadata, recipient consent and transfer status in sync.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';
lock table public.task_reassignment_requests in access exclusive mode;

-- Remove only the superseded workflow triggers inside this transaction. Recreate
-- the current guards before commit; no application writes can bypass them.
drop trigger if exists task_reassignment_consent_guard on public.task_reassignment_requests;
drop trigger if exists task_reassignment_guard on public.task_reassignment_requests;
drop trigger if exists reassignment_messages on public.task_reassignment_requests;

alter table public.task_reassignment_requests
    add column if not exists admin_decision text not null default 'pending',
    add column if not exists handoff_completed_at timestamptz,
    add column if not exists legacy_recipient_response jsonb,
    add column if not exists initiated_by_profile_id uuid references public.profiles(id);
alter table public.task_reassignment_requests
    drop constraint if exists task_reassignment_review_state,
    drop constraint if exists task_reassignment_requests_check,
    drop constraint if exists task_reassignment_requests_admin_decision_check;

-- Preserve completed legacy decisions. Never transfer task ownership in a repair.
update public.task_reassignment_requests
set admin_decision = status
where admin_decision = 'pending' and status in ('approved', 'rejected');
update public.task_reassignment_requests
set handoff_completed_at = updated_at
where status = 'approved' and handoff_completed_at is null;

-- An acceptance before admin review is not consent to the new workflow.
-- Archive it without overwriting history; the recipient must respond after review.
update public.task_reassignment_requests
set legacy_recipient_response = coalesce(legacy_recipient_response, jsonb_build_object(
        'decision', recipient_decision, 'profile_id', responded_by_profile_id,
        'responded_at', responded_at)),
    recipient_decision = 'pending', responded_by_profile_id = null, responded_at = null
where status = 'pending' and admin_decision = 'pending' and recipient_decision = 'accepted';

alter table public.task_reassignment_requests
    alter column admin_decision set default 'pending',
    alter column admin_decision set not null,
    add constraint task_reassignment_requests_admin_decision_check
        check (admin_decision in ('pending', 'approved', 'rejected')),
    add constraint task_reassignment_review_state check (
        (admin_decision = 'pending'
            and reviewed_by_profile_id is null and reviewed_at is null)
        or (admin_decision in ('approved', 'rejected')
            and reviewed_by_profile_id is not null and reviewed_at is not null)
    );

-- These definitions match the admin-first migration, without its one-time renames.
create or replace function public.guard_task_reassignment_request() returns trigger
language plpgsql set search_path='' as $$
declare t public.tasks; proposed_name text;
begin
 if tg_op='INSERT' then
  if new.status<>'pending' or new.admin_decision<>'pending' or new.recipient_decision<>'pending'
   or new.reviewed_by_profile_id is not null or new.responded_by_profile_id is not null
   or new.reviewed_at is not null or new.responded_at is not null or new.handoff_completed_at is not null
   or to_jsonb(new)->>'archived_at' is not null or to_jsonb(new)->>'archived_by_profile_id' is not null
   then raise exception 'New requests must await admin review'; end if;
  select * into strict t from public.tasks where id=new.task_id for update;
  if t.status='done' then raise exception 'Completed tasks cannot be reassigned'; end if;
  if not exists(select 1 from public.members where code=new.requester_code and active)
   or not exists(select 1 from public.members where code=new.proposed_assignee_code and active) then
   raise exception 'Requester and proposed assignee must be active'; end if;
  if new.proposed_assignee_code=t.owner_code then raise exception 'Proposed assignee already owns the task'; end if;
  new.previous_owner_code:=t.owner_code; new.previous_assignee_text:=t.assignee_text;
  new.initiated_by_profile_id:=auth.uid(); new.created_at:=now();
 else
  -- Older installations can apply this repair before adding request archives.
  if to_jsonb(new)->>'archived_at' is distinct from to_jsonb(old)->>'archived_at' then
   if old.status not in ('approved','rejected','declined')
    or (to_jsonb(new) - array['archived_at','archived_by_profile_id'])
        is distinct from (to_jsonb(old) - array['archived_at','archived_by_profile_id'])
    or public.current_board_member_code() is null
    or not exists(select 1 from public.profiles where id=auth.uid() and is_admin) then
    raise exception 'Only active admins can archive resolved requests'; end if;
   new.archived_by_profile_id:=case when new.archived_at is null then null else auth.uid() end;
   new.updated_at:=now();
   return new;
  end if;
  if to_jsonb(new)->>'archived_by_profile_id' is distinct from to_jsonb(old)->>'archived_by_profile_id' then
   raise exception 'Archive metadata cannot be changed separately'; end if;
  if old.status<>'pending' then raise exception 'Request has already been answered or closed'; end if;
  if row(new.task_id,new.requester_code,new.proposed_assignee_code,new.reason,new.previous_owner_code,
    new.previous_assignee_text,new.initiated_by_profile_id,new.legacy_recipient_response,new.handoff_completed_at)
   is distinct from row(old.task_id,old.requester_code,old.proposed_assignee_code,old.reason,old.previous_owner_code,
    old.previous_assignee_text,old.initiated_by_profile_id,old.legacy_recipient_response,old.handoff_completed_at) then
   raise exception 'Submitted request details cannot be changed'; end if;
  new.created_at:=old.created_at;
  if new.admin_decision is distinct from old.admin_decision then
   if old.admin_decision<>'pending' or not public.can_review_task_requests()
    or new.reviewed_by_profile_id is distinct from auth.uid()
    or new.admin_decision not in ('approved','rejected')
    or new.recipient_decision<>'pending' then raise exception 'Only an admin can review a pending proposal'; end if;
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
    or new.recipient_decision not in ('accepted','denied') then raise exception 'Only the proposed recipient can respond'; end if;
   new.responded_at:=now();
  end if;
  if new.status is distinct from (case when new.admin_decision='rejected' then 'rejected'
    when new.recipient_decision='denied' then 'declined'
    when new.admin_decision='approved' and new.recipient_decision='accepted' then 'approved' else 'pending' end) then
   raise exception 'Invalid transfer stage'; end if;
  if new.admin_decision='approved' and (old.admin_decision<>'approved' or new.status='approved') then
   select * into strict t from public.tasks where id=new.task_id for update;
   if t.status='done' then raise exception 'Completed tasks cannot be reassigned'; end if;
   if row(t.owner_code,t.assignee_text) is distinct from row(old.previous_owner_code,old.previous_assignee_text) then
    raise exception 'Task assignment changed; ask for a new request'; end if;
  end if;
  if new.status='approved' then
   select display_name into proposed_name from public.members where code=new.proposed_assignee_code and active;
   if proposed_name is null then raise exception 'Proposed assignee must be active'; end if;
   if not exists(select 1 from public.profiles p join public.members m on m.code=p.member_code
    where p.id=new.reviewed_by_profile_id and m.active and m.contact_consent and p.password_setup_complete
    and (p.is_admin or lower(trim(m.board_role)) in ('president','vice president'))) then
    raise exception 'Administrator approval is no longer authorized'; end if;
   update public.tasks set owner_code=new.proposed_assignee_code,assignee_text=proposed_name where id=new.task_id;
   new.handoff_completed_at:=now();
  end if;
 end if;
 new.updated_at:=now(); return new;
end;
$$;

create or replace function public.review_task_reassignment(p_request_id uuid,p_decision text,p_review_note text default '')
returns public.task_reassignment_requests language plpgsql security definer set search_path='' as $$
declare r public.task_reassignment_requests;
begin
 if not public.can_review_task_requests() then raise exception 'Only the president, VP, or an admin can review requests'; end if;
 if p_decision is null or p_decision not in ('approved','rejected') then raise exception 'Decision must be approved or rejected'; end if;
 select * into r from public.task_reassignment_requests where id=p_request_id for update;
 if not found or r.status<>'pending' or r.admin_decision<>'pending' then raise exception 'Pending admin review not found'; end if;
 update public.task_reassignment_requests set admin_decision=p_decision,
  status=case when p_decision='rejected' then 'rejected' else 'pending' end,
  reviewed_by_profile_id=auth.uid(),review_note=p_review_note where id=p_request_id returning * into r;
 return r;
end;
$$;

create or replace function public.respond_task_reassignment(p_request_id uuid,p_decision text)
returns public.task_reassignment_requests language plpgsql security definer set search_path='' as $$
declare member text:=public.current_board_member_code(); r public.task_reassignment_requests;
begin
 if member is null then raise exception 'A verified active member is required'; end if;
 if p_decision is null or p_decision not in ('accepted','denied') then raise exception 'Response must be accepted or denied'; end if;
 select * into r from public.task_reassignment_requests where id=p_request_id for update;
 if not found or r.proposed_assignee_code<>member then raise exception 'Incoming request not found'; end if;
 if r.status<>'pending' or r.recipient_decision<>'pending' then raise exception 'This request has already been answered or closed'; end if;
 if r.admin_decision<>'approved' then raise exception 'Administrator approval is required before recipient consent'; end if;
 update public.task_reassignment_requests set recipient_decision=p_decision,responded_by_profile_id=auth.uid(),
  responded_at=now(),status=case when p_decision='accepted' then 'approved' else 'declined' end
  where id=p_request_id returning * into r;
 return r;
end;
$$;

create or replace function public.queue_reassignment_messages() returns trigger
language plpgsql security definer set search_path='' as $$
declare t public.tasks; body text;
begin
 select * into strict t from public.tasks where id=new.task_id;
 if new.status='pending' and new.admin_decision='pending' then
  insert into public.reassignment_notifications(request_id,event,recipient_code,body)
   select new.id,'admin_review',m.code,format('Winnie REQ-%s: requested transfer of "%s" (%s) to %s. Review first: approve REQ-%s / reject REQ-%s. Ownership stays unchanged until the recipient accepts after approval.',
    new.request_no,left(t.title,200),t.task_code,(select display_name from public.members where code=new.proposed_assignee_code),new.request_no,new.request_no)
   from public.profiles p join public.members m on m.code=p.member_code where m.active and m.contact_consent and p.password_setup_complete
    and (p.is_admin or lower(trim(m.board_role)) in ('president','vice president')) on conflict do nothing;
 elsif new.status='pending' and new.admin_decision='approved' then
  insert into public.reassignment_notifications(request_id,event,recipient_code,body)
   values(new.id,'recipient_consent',new.proposed_assignee_code,format('Winnie REQ-%s: an administrator approved offering you "%s" (%s), due %s. Accept or deny: accept REQ-%s / deny REQ-%s. Ownership transfers only if you accept.',
    new.request_no,left(t.title,200),t.task_code,coalesce(t.due_date::text,'not set'),new.request_no,new.request_no)) on conflict do nothing;
 elsif new.status in ('approved','rejected','declined') and old.status='pending' then
  update public.task_help_requests set status=case when new.status='approved' then 'cancelled' else 'denied' end,
   revision=revision+1 where reassignment_id=new.id and status='pending_approval';
  body:=format('Winnie REQ-%s for "%s" (%s): %s. %s',new.request_no,left(t.title,200),t.task_code,new.status,
   case when new.status='approved' then 'Ownership transferred after admin approval and recipient consent. The outgoing owner remains in transfer history.' else 'Ownership is unchanged.' end);
  insert into public.reassignment_notifications(request_id,event,recipient_code,body)
   select new.id,'decision_v2',code,body from (values(new.requester_code),(new.proposed_assignee_code)) recipients(code) on conflict do nothing;
 end if;
 return new;
end;
$$;

create or replace function public.claim_reassignment_notification() returns jsonb
language plpgsql security definer set search_path='' as $$
declare n public.reassignment_notifications; token uuid; destination text;
begin
 update public.reassignment_notifications set status='uncertain' where status='sending' and started_at<now()-interval '2 minutes';
 update public.reassignment_notifications notice set status='cancelled' from public.task_reassignment_requests r
  where notice.request_id=r.id and notice.status='pending' and (
   (notice.event='admin_review' and (r.status<>'pending' or r.admin_decision<>'pending'))
   or (notice.event='recipient_consent' and (r.status<>'pending' or r.admin_decision<>'approved' or r.recipient_decision<>'pending')));
 select n1.* into n from public.reassignment_notifications n1 where n1.status='pending' and exists(
  select 1 from public.member_identities i join public.members m on m.code=i.member_code where m.code=n1.recipient_code
   and m.active and m.contact_consent and i.platform='imessage' and i.reminders_enabled)
  order by n1.id for update skip locked limit 1;
 if not found then return null; end if;
 select sender_id into destination from public.member_identities where member_code=n.recipient_code and platform='imessage' and reminders_enabled order by sender_id limit 1;
 token:=gen_random_uuid(); update public.reassignment_notifications set status='sending',claim_token=token,started_at=now() where id=n.id;
 return jsonb_build_object('id',n.id,'claim_token',token,'kind','dm','recipient',destination,'text',n.body);
end;
$$;

-- Retain the same RPC permissions; neither anonymous users nor ordinary members
-- gain administrator privileges. Identity still comes from auth.uid().
revoke all on function public.guard_task_reassignment_request() from public, anon, authenticated;
revoke all on function public.queue_reassignment_messages() from public, anon, authenticated;
revoke all on function public.review_task_reassignment(uuid,text,text) from public, anon;
revoke all on function public.respond_task_reassignment(uuid,text) from public, anon;
grant execute on function public.review_task_reassignment(uuid,text,text) to authenticated;
grant execute on function public.respond_task_reassignment(uuid,text) to authenticated;
revoke all on function public.claim_reassignment_notification() from public, anon, authenticated;
grant execute on function public.claim_reassignment_notification() to service_role;

create trigger task_reassignment_guard before insert or update
on public.task_reassignment_requests for each row
execute function public.guard_task_reassignment_request();
create trigger reassignment_messages after insert or update
on public.task_reassignment_requests for each row
execute function public.queue_reassignment_messages();

-- The archive shipped separately. Keep its access check in sync with roster activation.
do $$
begin
 if to_regprocedure('public.archive_task_reassignment(uuid,boolean)') is not null then
  execute $policy$
   alter policy task_reassignment_read on public.task_reassignment_requests using (
    public.current_board_member_code() is not null and (
     exists (select 1 from public.profiles where id=auth.uid() and is_admin)
     or (archived_at is null and (public.can_review_task_requests()
      or requester_code=public.current_board_member_code()
      or proposed_assignee_code=public.current_board_member_code()))
    )
   )
  $policy$;
  execute $function$
   create or replace function public.archive_task_reassignment(p_request_id uuid, p_archive boolean default true)
   returns public.task_reassignment_requests
   language plpgsql security definer set search_path='' as $body$
   declare saved public.task_reassignment_requests;
   begin
    if public.current_board_member_code() is null
     or not exists(select 1 from public.profiles where id=auth.uid() and is_admin) then
     raise exception 'Only active admins can archive task reassignment requests'; end if;
    if p_archive is null then raise exception 'Archive choice is required'; end if;
    select * into saved from public.task_reassignment_requests
     where id=p_request_id and status in ('approved','rejected','declined') for update;
    if not found then raise exception 'Only resolved requests can be archived'; end if;
    if (saved.archived_at is not null) = p_archive then return saved; end if;
    update public.task_reassignment_requests set archived_at=case when p_archive then now() else null end
     where id=p_request_id returning * into saved;
    return saved;
   end;
   $body$
  $function$;
 end if;
end;
$$;

-- Retire unsent messages from the old recipient-first workflow. Do not enqueue
-- or send anything during this repair; subsequent user actions use the new queue.
update public.reassignment_notifications
set status = 'cancelled'
where status = 'pending' and event in ('incoming', 'review');

comment on table public.task_reassignment_requests is
    'Admin review first; recipient consent second; completed handoffs retain original owner and outgoing-owner history.';
notify pgrst, 'reload schema';
commit;
