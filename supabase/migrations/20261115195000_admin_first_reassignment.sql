-- Admin authorizes the proposal first; the recipient's subsequent consent commits transfer.
begin;
alter table public.task_reassignment_requests disable trigger task_reassignment_consent_guard;
alter table public.task_reassignment_requests disable trigger task_reassignment_guard;
alter table public.task_reassignment_requests add column admin_decision text not null default 'pending'
 check(admin_decision in ('pending','approved','rejected')),
 add column handoff_completed_at timestamptz,
 add column legacy_recipient_response jsonb,
 add column initiated_by_profile_id uuid references public.profiles(id);
alter table public.task_reassignment_requests drop constraint task_reassignment_review_state;
update public.task_reassignment_requests set admin_decision=case when status='approved' then 'approved'
 when status='rejected' then 'rejected' else 'pending' end,
 handoff_completed_at=case when status='approved' then updated_at else null end;
-- Preserve pre-upgrade responses, but ask again after admin authorization on open proposals.
update public.task_reassignment_requests set legacy_recipient_response=jsonb_build_object(
 'decision',recipient_decision,'profile_id',responded_by_profile_id,'responded_at',responded_at),
 recipient_decision='pending',responded_by_profile_id=null,responded_at=null
 where status='pending' and recipient_decision='accepted';
alter table public.task_reassignment_requests add constraint task_reassignment_review_state check(
 (admin_decision='pending' and reviewed_by_profile_id is null and reviewed_at is null)
 or (admin_decision in ('approved','rejected') and reviewed_by_profile_id is not null and reviewed_at is not null));
drop trigger task_reassignment_consent_guard on public.task_reassignment_requests;
create or replace function public.guard_task_reassignment_request() returns trigger
language plpgsql set search_path='' as $$
declare t public.tasks; proposed_name text;
begin
 if tg_op='INSERT' then
  if new.status<>'pending' or new.admin_decision<>'pending' or new.recipient_decision<>'pending'
   or new.reviewed_by_profile_id is not null or new.responded_by_profile_id is not null
   or new.reviewed_at is not null or new.responded_at is not null or new.handoff_completed_at is not null
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
alter table public.task_reassignment_requests enable trigger task_reassignment_guard;

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

-- Existing server adapters continue to verify message identity and own the replay receipts.
alter function public.reassignment_as_member(text,text,jsonb) rename to reassignment_as_member_v1;
revoke all on function public.reassignment_as_member_v1(text,text,jsonb) from public,anon,authenticated,service_role;
create function public.reassignment_as_member(p_actor text,p_action text,p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare answer jsonb; decision text;
begin
 answer:=public.reassignment_as_member_v1(p_actor,p_action,p_payload);
 select admin_decision into decision from public.task_reassignment_requests where request_no=(answer->>'request_no')::bigint;
 return answer||jsonb_build_object('admin_decision',decision);
end;
$$;
revoke all on function public.reassignment_as_member(text,text,jsonb) from public,anon,authenticated;
grant execute on function public.reassignment_as_member(text,text,jsonb) to service_role;
-- Enrich list results, preserving the existing verified sender and replay boundary.
alter function public.messaging_reassignment(text,text,text,text,jsonb) rename to messaging_reassignment_v1;
revoke all on function public.messaging_reassignment_v1(text,text,text,text,jsonb) from public,anon,authenticated,service_role;
create function public.messaging_reassignment(p_platform text,p_sender_id text,p_message_id text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare answer jsonb;
begin
 answer:=public.messaging_reassignment_v1(p_platform,p_sender_id,p_message_id,p_action,p_payload);
 if p_action='list' then
  return jsonb_build_object('requests',coalesce((select jsonb_agg(item||jsonb_build_object('admin_decision',r.admin_decision))
   from jsonb_array_elements(answer->'requests') item join public.task_reassignment_requests r
    on r.request_no=(item->>'request_no')::bigint),'[]'));
 end if;
 return answer;
end;
$$;
revoke all on function public.messaging_reassignment(text,text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.messaging_reassignment(text,text,text,text,jsonb) to service_role;

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
-- Retire open messages advertising the previous order and seed admin review for open requests.
update public.reassignment_notifications n set status='cancelled' from public.task_reassignment_requests r
 where n.request_id=r.id and r.status='pending' and n.status='pending';
update public.task_reassignment_requests set updated_at=updated_at where status='pending';

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
-- The legacy HELP selector delegates to the current queue; update only its obsolete copy.
do $$ declare definition text; begin
 select pg_get_functiondef('public.help_transition(bigint,integer,text,text,jsonb,text,text)'::regprocedure) into definition;
 definition:=replace(definition,'after recipient acceptance','before recipient consent');
 definition:=replace(definition,'The recipient must accept in Requests or text accept REQ-%s, then an admin can approve. Ownership is unchanged.',
  'An admin reviews first. After approval, the recipient can consent in Requests or text accept REQ-%s. Ownership is unchanged until both steps finish.');
 execute definition;
end $$;
comment on table public.task_reassignment_requests is 'Admin review first; recipient consent second; completed handoffs retain original owner and outgoing-owner history.';
notify pgrst,'reload schema';
commit;
