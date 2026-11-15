-- One consent-based queue for browser and verified Photon messages.
begin;
alter table public.task_reassignment_requests add column request_no bigint generated always as identity unique;
grant usage,select on sequence public.task_reassignment_requests_request_no_seq to service_role;
alter table public.task_help_requests add column reassignment_id uuid references public.task_reassignment_requests(id);

-- Trusted server-only adapter. The actor comes from a verified messaging identity,
-- never Gemini or a browser-supplied member code. Restore the caller's JWT subject.
create function public.reassignment_as_member(p_actor text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare profile uuid; prior text:=current_setting('request.jwt.claim.sub',true);
 r public.task_reassignment_requests; t public.tasks;
begin
 select p.id into strict profile from public.profiles p join public.members m on m.code=p.member_code
 join auth.users u on u.id=p.id where m.code=p_actor and m.active and m.contact_consent
 and p.password_setup_complete and u.email_confirmed_at is not null
 and m.email=lower(trim(u.email)) and lower(trim(p.email))=m.email;
 perform set_config('request.jwt.claim.sub',profile::text,true);
 if p_action='submit' then
  select * into strict t from public.tasks where id=(p_payload->>'task_id')::uuid for update;
  if t.semester_code is distinct from p_payload->>'semester' or t.status='done'
    or (t.owner_code is distinct from p_actor and not (t.owner_code is null and exists(
      select 1 from public.member_aliases a where a.semester_code=t.semester_code
      and lower(trim(a.alias))=lower(trim(t.assignee_text)) and a.member_code=p_actor))) then
   raise exception 'Only the verified current task owner can request this transfer';
  end if;
  select * into r from public.task_reassignment_requests where task_id=t.id
   and requester_code=p_actor and status='pending' for update;
  if found then
   if r.proposed_assignee_code is distinct from p_payload->>'proposed_code' then
    raise exception 'A different transfer is already pending for this task';
   end if;
  else
   r:=public.submit_task_reassignment(t.id,p_payload->>'proposed_code',coalesce(p_payload->>'reason','Requested through Photon'));
  end if;
 elsif p_action in ('accepted','denied','approved','rejected') then
  select * into r from public.task_reassignment_requests where request_no=(p_payload->>'request_no')::bigint;
  if not found then raise exception 'Request not found'; end if;
  if p_action in ('accepted','denied') then r:=public.respond_task_reassignment(r.id,p_action);
  else r:=public.review_task_reassignment(r.id,p_action,'Reviewed through Photon'); end if;
 else raise exception 'Unsupported reassignment action'; end if;
 perform set_config('request.jwt.claim.sub',coalesce(prior,''),true);
 return jsonb_build_object('request_no',r.request_no,'status',r.status,'recipient_decision',r.recipient_decision);
exception when no_data_found or too_many_rows then
 perform set_config('request.jwt.claim.sub',coalesce(prior,''),true);
 raise exception 'A verified roster-linked account with completed password setup is required';
when others then
 perform set_config('request.jwt.claim.sub',coalesce(prior,''),true); raise;
end;
$$;
revoke all on function public.reassignment_as_member(text,text,jsonb) from public,anon,authenticated;
grant execute on function public.reassignment_as_member(text,text,jsonb) to service_role;

create table public.reassignment_message_receipts (
 platform text not null,message_id text not null,sender_id text not null,
 payload jsonb not null,result jsonb not null,primary key(platform,message_id)
);
alter table public.reassignment_message_receipts enable row level security;
revoke all on public.reassignment_message_receipts from public,anon,authenticated;
grant all on public.reassignment_message_receipts to service_role;

create function public.messaging_reassignment(p_platform text,p_sender_id text,p_message_id text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare actor text; prior public.reassignment_message_receipts; answer jsonb;
begin
 if p_platform<>'imessage' or nullif(trim(p_message_id),'') is null or length(p_message_id)>500
    or length(p_sender_id)>500 or jsonb_typeof(p_payload)<>'object' then raise exception 'Verified message metadata is required'; end if;
 select m.code into actor from public.member_identities i join public.members m on m.code=i.member_code
 where i.platform=p_platform and i.sender_id=p_sender_id and m.active and m.contact_consent for update of m;
 if actor is null then raise exception 'Your messaging account is not linked to an active consenting member'; end if;
 select * into prior from public.reassignment_message_receipts where platform=p_platform and message_id=p_message_id;
 if found then
  if prior.sender_id<>p_sender_id or prior.payload<>jsonb_build_object('action',p_action,'data',p_payload) then
   raise exception 'Message identity or content changed'; end if;
  return prior.result;
 end if;
 if p_action='list' then
  select jsonb_build_object('requests',coalesce(jsonb_agg(jsonb_build_object(
   'request_no',r.request_no,'task_code',t.task_code,'title',t.title,'status',r.status,
   'recipient_decision',r.recipient_decision,'incoming',r.proposed_assignee_code=actor)), '[]'::jsonb)) into answer
  from (select * from public.task_reassignment_requests where status='pending' and
   (requester_code=actor or proposed_assignee_code=actor or exists(select 1 from public.profiles p
    where p.member_code=actor and p.is_admin and p.password_setup_complete)) order by request_no desc limit 20) r
   join public.tasks t on t.id=r.task_id;
 else answer:=public.reassignment_as_member(actor,p_action,p_payload); end if;
 insert into public.reassignment_message_receipts values(p_platform,p_message_id,p_sender_id,
  jsonb_build_object('action',p_action,'data',p_payload),answer);
 return answer;
end;
$$;
revoke all on function public.messaging_reassignment(text,text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.messaging_reassignment(text,text,text,text,jsonb) to service_role;

-- Retire the old ownership-changing path, while reusing its saved recommendations.
alter function public.help_transition(bigint,integer,text,text,jsonb,text,text) rename to help_transition_legacy;
revoke all on function public.help_transition_legacy(bigint,integer,text,text,jsonb,text,text) from public,anon,authenticated,service_role;
create function public.help_transition(p_request bigint,p_revision integer,p_action text,p_actor text,
 p_candidates jsonb default '[]',p_selected text default null,p_assignee text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare h public.task_help_requests; t public.tasks; answer jsonb; request_id uuid;
begin
 if p_action in ('approve','deny') then
  raise exception 'Legacy approval is disabled. Use the shared Requests queue or approve/reject REQ-number after recipient acceptance';
 end if;
 if p_action='candidates' then
  return public.help_transition_legacy(p_request,p_revision,p_action,p_actor,p_candidates,p_selected,p_assignee);
 end if;
 if p_action<>'select' then raise exception 'Unsupported help action'; end if;
 select t1.* into strict t from public.tasks t1 join public.task_help_requests h1 on h1.task_id=t1.id
 where h1.request_no=p_request for update of t1;
 select * into strict h from public.task_help_requests where request_no=p_request for update;
 if h.requester_code is distinct from p_actor then raise exception 'Not the requester'; end if;
 if h.reassignment_id is not null then
  select jsonb_build_object('reply',format('Already saved as REQ-%s. Open Requests to check its status.',request_no))
   into answer from public.task_reassignment_requests where id=h.reassignment_id;
  return answer;
 end if;
 if h.revision<>p_revision or h.status<>'suggestions_ready' or t.updated_at is distinct from h.task_version then
  raise exception 'Task or request changed. Request fresh suggestions'; end if;
 if not exists(select 1 from jsonb_array_elements(h.candidates) c where c->>'code'=p_selected)
  then raise exception 'Choose a saved suggested member'; end if;
 answer:=public.reassignment_as_member(p_actor,'submit',jsonb_build_object(
  'task_id',t.id,'semester',t.semester_code,'proposed_code',p_selected,'reason',format('Selected from HELP-%s suggestions',p_request)));
 select id into strict request_id from public.task_reassignment_requests where request_no=(answer->>'request_no')::bigint;
 update public.task_help_requests set reassignment_id=request_id,selected_code=p_selected,status='pending_approval',revision=revision+1
 where request_no=p_request;
 return jsonb_build_object('reply',format('Saved REQ-%s. The recipient must accept in Requests or text accept REQ-%s, then an admin can approve. Ownership is unchanged.',answer->>'request_no',answer->>'request_no'));
end;
$$;
revoke all on function public.help_transition(bigint,integer,text,text,jsonb,text,text) from public,anon,authenticated;
grant execute on function public.help_transition(bigint,integer,text,text,jsonb,text,text) to service_role;
-- Old unsent approval messages must not advertise a consent-bypassing command.
update public.help_notifications set status='cancelled' where status='pending' and dedupe_key like 'review:%';

create table public.reassignment_notifications (
 id uuid primary key default gen_random_uuid(),request_id uuid not null references public.task_reassignment_requests(id),
 event text not null,recipient_code text not null references public.members(code),body text not null check(length(body)<=2000),
 status text not null default 'pending' check(status in ('pending','sending','sent','uncertain','cancelled')),
 claim_token uuid,started_at timestamptz,provider_id text,unique(request_id,event,recipient_code)
);
alter table public.reassignment_notifications enable row level security;
revoke all on public.reassignment_notifications from public,anon,authenticated;
grant all on public.reassignment_notifications to service_role;
create function public.queue_reassignment_messages() returns trigger language plpgsql security definer set search_path='' as $$
declare t public.tasks; body text;
begin
 select * into strict t from public.tasks where id=new.task_id;
 if tg_op='INSERT' then
  insert into public.reassignment_notifications(request_id,event,recipient_code,body) values(new.id,'incoming',new.proposed_assignee_code,
   format('Winnie REQ-%s: proposed task "%s" (%s), due %s. Open Requests to Accept/Deny, or text accept REQ-%s / deny REQ-%s. Acceptance still requires admin approval.',new.request_no,left(t.title,200),t.task_code,coalesce(t.due_date::text,'not set'),new.request_no,new.request_no)) on conflict do nothing;
 elsif new.status='pending' and new.recipient_decision='accepted' and old.recipient_decision<>'accepted' then
  insert into public.reassignment_notifications(request_id,event,recipient_code,body)
   select new.id,'review',m.code,format('Winnie REQ-%s: recipient accepted "%s" (%s). Review in Requests, or text approve REQ-%s / reject REQ-%s.',new.request_no,left(t.title,200),t.task_code,new.request_no,new.request_no)
   from public.profiles p join public.members m on m.code=p.member_code where m.active and m.contact_consent and p.password_setup_complete
   and (p.is_admin or lower(trim(m.board_role)) in ('president','vice president')) on conflict do nothing;
 elsif new.status in ('approved','rejected','declined') and old.status='pending' then
  update public.task_help_requests set status=case when new.status='approved' then 'cancelled' else 'denied' end,
   revision=revision+1 where reassignment_id=new.id and status='pending_approval';
  body:=format('Winnie REQ-%s for "%s" (%s): %s. %s',new.request_no,left(t.title,200),t.task_code,new.status,
   case when new.status='approved' then 'Ownership transferred after recipient acceptance and admin approval.' else 'Ownership is unchanged.' end);
  insert into public.reassignment_notifications(request_id,event,recipient_code,body)
   select new.id,'decision',code,body from (values(new.requester_code),(new.proposed_assignee_code)) recipients(code)
   on conflict do nothing;
 end if;
 return new;
end;
$$;
revoke all on function public.queue_reassignment_messages() from public,anon,authenticated;
create trigger reassignment_messages after insert or update on public.task_reassignment_requests for each row execute function public.queue_reassignment_messages();

create function public.claim_reassignment_notification() returns jsonb language plpgsql security definer set search_path='' as $$
declare n public.reassignment_notifications; token uuid; destination text;
begin
 update public.reassignment_notifications set status='uncertain' where status='sending' and started_at<now()-interval '2 minutes';
 update public.reassignment_notifications notice set status='cancelled' from public.task_reassignment_requests r where notice.request_id=r.id
 and notice.status='pending' and ((notice.event='incoming' and (r.status<>'pending' or r.recipient_decision<>'pending'))
 or (notice.event='review' and (r.status<>'pending' or r.recipient_decision<>'accepted')));
 select n1.* into n from public.reassignment_notifications n1 where status='pending' and exists(
  select 1 from public.member_identities i join public.members m on m.code=i.member_code where m.code=n1.recipient_code
  and m.active and m.contact_consent and i.platform='imessage' and i.reminders_enabled)
 order by n1.id for update skip locked limit 1;
 if not found then return null; end if;
 select i.sender_id into destination from public.member_identities i where i.member_code=n.recipient_code
 and i.platform='imessage' and i.reminders_enabled order by i.sender_id limit 1;
 token:=gen_random_uuid();
 update public.reassignment_notifications set status='sending',claim_token=token,started_at=now() where id=n.id;
 return jsonb_build_object('id',n.id,'claim_token',token,'kind','dm','recipient',destination,'text',n.body);
end;
$$;
create function public.finish_reassignment_notification(p_id uuid,p_token uuid,p_outcome text,p_provider_id text) returns text
language plpgsql security definer set search_path='' as $$
declare n public.reassignment_notifications;
begin
 select * into n from public.reassignment_notifications where id=p_id for update;
 if not found then return 'not_found'; end if;
 if p_outcome not in ('sent','uncertain') or (p_outcome='sent' and nullif(p_provider_id,'') is null) then raise exception 'Invalid notification result'; end if;
 if n.claim_token is distinct from p_token then return 'ignored'; end if;
 if n.status='sent' then return 'sent'; end if;
 if n.status<>'sending' then return 'ignored'; end if;
 update public.reassignment_notifications set status=p_outcome,provider_id=p_provider_id where id=p_id;
 return p_outcome;
end;
$$;
revoke all on function public.claim_reassignment_notification() from public,anon,authenticated;
revoke all on function public.finish_reassignment_notification(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.claim_reassignment_notification() to service_role;
grant execute on function public.finish_reassignment_notification(uuid,uuid,text,text) to service_role;

-- Carry forward eligible pending HELP proposals without approving them. Requests whose
-- identities/ownership need review stay in history; no contact or role is invented.
do $$
declare h record; answer jsonb;
begin
 for h in select h1.request_no,h1.requester_code,h1.selected_code,t.id,t.semester_code
  from public.task_help_requests h1 join public.tasks t on t.id=h1.task_id
  where h1.status='pending_approval' and h1.reassignment_id is null and h1.selected_code is not null loop
  begin
   answer:=public.reassignment_as_member(h.requester_code,'submit',jsonb_build_object(
    'task_id',h.id,'semester',h.semester_code,'proposed_code',h.selected_code,'reason',format('Migrated HELP-%s proposal',h.request_no)));
   update public.task_help_requests set reassignment_id=(select id from public.task_reassignment_requests
    where request_no=(answer->>'request_no')::bigint) where request_no=h.request_no;
  exception when raise_exception or no_data_found or too_many_rows then null;
  end;
 end loop;
end;
$$;
insert into public.reassignment_notifications(request_id,event,recipient_code,body)
 select r.id,'incoming',r.proposed_assignee_code,
  format('Winnie REQ-%s: proposed task "%s" (%s). Open Requests to Accept/Deny, or text accept REQ-%s / deny REQ-%s. Admin approval is still required.',
   r.request_no,left(t.title,200),t.task_code,r.request_no,r.request_no)
 from public.task_reassignment_requests r join public.tasks t on t.id=r.task_id
 where r.status='pending' and r.recipient_decision='pending' on conflict do nothing;
notify pgrst,'reload schema';
commit;
