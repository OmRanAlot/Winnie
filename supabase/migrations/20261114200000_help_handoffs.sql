-- Server-only reassignment workflow. Model suggestions never authorize a transfer.
begin;
alter table public.members add column messaging_admin boolean not null default false;
alter table public.task_help_requests drop constraint task_help_requests_status_check;
alter table public.task_help_requests add constraint task_help_requests_status_check check
 (status in ('awaiting_recommendations','suggestions_ready','pending_approval',
             'approved_group_pending','group_active','denied','cancelled'));
alter table public.task_help_requests add column candidates jsonb not null default '[]';
alter table public.task_help_requests add column selected_code text references public.members(code);
alter table public.task_help_requests add column group_id text unique;
alter table public.task_help_requests add column approved_by text;

create table public.help_notifications (
 id uuid primary key default gen_random_uuid(),
 request_no bigint not null references public.task_help_requests(request_no) on delete cascade,
 dedupe_key text not null unique,
 kind text not null check (kind in ('dm','group')),
 recipient_code text references public.members(code),
 body text not null check (length(body) between 1 and 2000),
 status text not null default 'pending' check (status in ('pending','sending','sent','uncertain','cancelled')),
 claim_token uuid,
 started_at timestamptz,
 provider_id text
);
alter table public.help_notifications enable row level security;
revoke all on public.help_notifications from public,anon,authenticated;
grant all on public.help_notifications to service_role;

-- A task edit invalidates an unapproved request. Approved handoffs survive their
-- own assignment update, but changes after group creation invalidate that binding.
create or replace function public.invalidate_help_requests() returns trigger
language plpgsql set search_path = '' as $$
declare handoff record;
begin
 if new.status='done' or new.due_date is distinct from old.due_date
    or new.assignee_text is distinct from old.assignee_text then
  update public.task_help_requests set status='cancelled',revision=revision+1
   where task_id=new.id and status in ('awaiting_recommendations','suggestions_ready','pending_approval');
  if new.due_date is distinct from old.due_date or new.assignee_text is distinct from old.assignee_text then
   update public.task_help_requests set status='cancelled',revision=revision+1
    where task_id=new.id and status in ('group_active','approved_group_pending')
     and request_no::text is distinct from current_setting('winnie.approving_help',true);
  end if;
  if new.status='done' then
   if old.status<>'done' then
    for handoff in select request_no from public.task_help_requests
      where task_id=new.id and status in ('group_active','approved_group_pending') loop
     perform public.help_queue_admins(handoff.request_no,'completed:'||handoff.request_no,
       format('HELP-%s: %s is now marked complete in Winnie.',handoff.request_no,new.task_code));
    end loop;
   end if;
   update public.task_help_requests set status='cancelled',revision=revision+1
    where task_id=new.id and status='approved_group_pending';
  end if;
 end if;
 return new;
end;
$$;

create function public.help_queue_admins(p_request bigint,p_event text,p_body text)
returns void language sql set search_path = '' as $$
 insert into public.help_notifications(request_no,dedupe_key,kind,recipient_code,body)
 select p_request,p_event || ':' || m.code,'dm',m.code,p_body
 from public.members m where m.active and m.messaging_admin
 on conflict (dedupe_key) do nothing;
$$;

create function public.help_transition(p_request bigint,p_revision integer,p_action text,
 p_actor text,p_candidates jsonb default '[]',p_selected text default null,
 p_assignee text default null) returns jsonb
language plpgsql set search_path = '' as $$
declare r public.task_help_requests%rowtype; t public.tasks%rowtype; response text;
begin
 -- Always task then request, matching task triggers and completion transactions.
 select t1.* into t from public.tasks t1 join public.task_help_requests r1 on r1.task_id=t1.id
  where r1.request_no=p_request for update of t1;
 select * into r from public.task_help_requests where request_no=p_request for update;
 if r.request_no is null then raise exception 'Help request not found'; end if;
 if r.revision<>p_revision then raise exception 'Request changed; refresh before deciding'; end if;
 if t.status='done' or t.updated_at is distinct from r.task_version
    or r.status in ('cancelled','denied','approved_group_pending','group_active')
  then raise exception 'Task or request changed'; end if;
 if p_action in ('candidates','select') and p_actor is distinct from r.requester_code
  then raise exception 'Not the requester'; end if;
 if p_action='candidates' then
  if r.status not in ('awaiting_recommendations','suggestions_ready') then raise exception 'Not accepting suggestions'; end if;
  if jsonb_typeof(p_candidates)<>'array' or jsonb_array_length(p_candidates)>3
   then raise exception 'Invalid candidates'; end if;
  update public.task_help_requests set candidates=p_candidates,status='suggestions_ready'
    where request_no=p_request returning * into r;
  response:='Suggestions saved';
 elsif p_action='select' then
  if r.status<>'suggestions_ready' or not exists(select 1 from jsonb_array_elements(r.candidates) c
      join public.members m on m.code=c->>'code' and m.active
      where c->>'code'=p_selected and m.code<>r.requester_code)
    then raise exception 'Choose a current suggested member'; end if;
  update public.task_help_requests set selected_code=p_selected,status='pending_approval',revision=revision+1
    where request_no=p_request returning * into r;
  perform public.help_queue_admins(p_request,'review:'||p_request||':'||r.revision,
    format('Reassignment request HELP-%s: "%s" (%s), %s -> %s. Reply approve HELP-%s v%s or deny HELP-%s v%s. Approval transfers ownership.',
      p_request,t.title,t.task_code,
      (select display_name from public.members where code=r.requester_code),
      (select display_name from public.members where code=p_selected),p_request,r.revision,p_request,r.revision));
  response:='Requested admin approval. Ownership has not changed.';
 elsif p_action in ('approve','deny') then
  -- NULL actor is reserved for the separately authenticated server admin API.
  if p_actor is not null and not exists(select 1 from public.members where code=p_actor and active and messaging_admin)
   then raise exception 'Not a messaging admin'; end if;
  if r.status<>'pending_approval' then raise exception 'Not pending approval'; end if;
  if p_action='deny' then
   update public.task_help_requests set status='denied' where request_no=p_request;
   response:='Reassignment denied; ownership is unchanged.';
  else
   if nullif(trim(p_assignee),'') is null or not exists(select 1 from public.members where code=r.selected_code and active)
    then raise exception 'New assignment is unavailable'; end if;
   update public.task_help_requests set status='approved_group_pending',approved_by=coalesce(p_actor,'admin-api')
    where request_no=p_request;
   perform pg_catalog.set_config('winnie.approving_help',p_request::text,true);
   update public.tasks set assignee_text=p_assignee where id=t.id returning * into t;
   perform pg_catalog.set_config('winnie.approving_help','',true);
   update public.task_help_requests set task_version=t.updated_at where request_no=p_request;
   insert into public.help_notifications(request_no,dedupe_key,kind,body)
    values(p_request,'group:'||p_request,'group',format('Winnie handoff HELP-%s: "%s" (%s), due %s. Ownership has transferred from %s to %s. Share progress here. Only the new owner can confirm completion with done %s.',
       p_request,t.title,t.task_code,t.due_date,
       (select display_name from public.members where code=r.requester_code),
       (select display_name from public.members where code=r.selected_code),t.task_code))
    on conflict(dedupe_key) do nothing;
   response:='Approved; ownership transferred. Group setup is pending a supported Photon connection.';
   insert into public.help_notifications(request_no,dedupe_key,kind,recipient_code,body)
    values(p_request,'decision:new-owner:'||p_request,'dm',r.selected_code,
      format('You are now responsible for "%s" (%s), due %s. An admin approved HELP-%s. Text tasks to view your work. A handoff group will follow when group messaging is available.',
        t.title,t.task_code,t.due_date,p_request)) on conflict(dedupe_key) do nothing;
  end if;
  insert into public.help_notifications(request_no,dedupe_key,kind,recipient_code,body)
   values(p_request,'decision:'||p_request,'dm',r.requester_code,response)
   on conflict(dedupe_key) do nothing;
 else raise exception 'Unknown help action'; end if;
 return jsonb_build_object('reply',response);
end;
$$;

create function public.claim_help_notification(p_groups_enabled boolean)
returns jsonb language plpgsql set search_path = '' as $$
declare n public.help_notifications%rowtype; r public.task_help_requests%rowtype;
 a text; b text; token uuid;
begin
 update public.help_notifications set status='uncertain'
  where status='sending' and started_at < now()-interval '2 minutes';
 select * into n from public.help_notifications h where status='pending'
   and (kind='dm' or p_groups_enabled)
   and (kind='group' or exists(select 1 from public.member_identities i join public.members m on m.code=i.member_code
     where m.code=h.recipient_code and m.active and i.platform='imessage' and i.reminders_enabled
       and (h.dedupe_key like 'decision:%' or m.messaging_admin)))
   and (kind='dm' or exists(select 1 from public.task_help_requests req
     join public.member_identities i1 on i1.member_code=req.requester_code and i1.platform='imessage' and i1.reminders_enabled
     join public.member_identities i2 on i2.member_code=req.selected_code and i2.platform='imessage' and i2.reminders_enabled
     join public.members m1 on m1.code=req.requester_code and m1.active
     join public.members m2 on m2.code=req.selected_code and m2.active
     where req.request_no=h.request_no and i1.sender_id<>i2.sender_id))
   order by id for update skip locked limit 1;
 if not found then return null; end if;
 select * into r from public.task_help_requests where request_no=n.request_no;
 if (n.dedupe_key like 'review:%' and r.status<>'pending_approval')
    or (n.kind='group' and (r.status<>'approved_group_pending' or not exists(
      select 1 from public.tasks where id=r.task_id and status<>'done' and updated_at=r.task_version))) then
  update public.help_notifications set status='cancelled' where id=n.id; return null;
 end if;
 if n.kind='dm' then
  select i.sender_id into a from public.member_identities i join public.members m on m.code=i.member_code
   where m.active and i.platform='imessage' and i.reminders_enabled and m.code=n.recipient_code;
 else
  select i.sender_id into a from public.member_identities i join public.members m on m.code=i.member_code
   where m.active and i.platform='imessage' and i.reminders_enabled and m.code=r.requester_code;
  select i.sender_id into b from public.member_identities i join public.members m on m.code=i.member_code
   where m.active and i.platform='imessage' and i.reminders_enabled and m.code=r.selected_code;
 end if;
 if a is null or (n.kind='group' and (b is null or a=b)) then return null; end if;
 token:=gen_random_uuid();
 update public.help_notifications set status='sending',claim_token=token,started_at=now() where id=n.id;
 return jsonb_build_object('id',n.id,'claim_token',token,'kind',n.kind,'text',n.body,
    'recipient',a,'second_recipient',b);
end;
$$;

-- Reserve the actual provider group before posting the introduction. Some providers
-- reuse a conversation for the same people: never silently bind it to another task.
create function public.bind_help_group(p_id uuid,p_token uuid,p_group_id text)
returns boolean language plpgsql set search_path = '' as $$
declare n public.help_notifications%rowtype; r public.task_help_requests%rowtype;
begin
 if nullif(p_group_id,'') is null then raise exception 'Missing group ID'; end if;
 select * into n from public.help_notifications where id=p_id for update;
 if not found or n.kind<>'group' or n.status<>'sending' or n.claim_token is distinct from p_token
  then raise exception 'Group action is not authorized'; end if;
 select * into r from public.task_help_requests where request_no=n.request_no for update;
 if r.group_id=p_group_id and r.status='group_active' then return true; end if;
 if r.status<>'approved_group_pending' or not exists(select 1 from public.tasks
    where id=r.task_id and updated_at=r.task_version and status<>'done')
   then raise exception 'Handoff changed'; end if;
 update public.task_help_requests set group_id=p_group_id,status='group_active' where request_no=r.request_no;
 update public.help_notifications set provider_id=p_group_id where id=p_id;
 return true;
end;
$$;

create function public.finish_help_notification(p_id uuid,p_token uuid,p_outcome text,p_provider_id text)
returns text language plpgsql set search_path = '' as $$
declare n public.help_notifications%rowtype;
begin
 if p_outcome not in ('sent','uncertain') or (p_outcome='sent' and nullif(p_provider_id,'') is null)
  then raise exception 'Invalid delivery result'; end if;
 select * into n from public.help_notifications where id=p_id for update;
 if not found or n.claim_token is distinct from p_token then return 'ignored'; end if;
 if n.status='sent' then return 'sent'; end if;
 if n.kind='group' and p_outcome='sent' and not exists(select 1 from public.task_help_requests
   where request_no=n.request_no and group_id=p_provider_id)
  then raise exception 'Group must be bound before posting its introduction'; end if;
 update public.help_notifications set status=p_outcome,provider_id=p_provider_id where id=p_id;
 return p_outcome;
end;
$$;

-- Known group updates are deduplicated; only verified participants can report them.
create table public.help_group_messages (
 platform text not null, message_id text not null, request_no bigint not null
 references public.task_help_requests(request_no) on delete cascade,
 summary text not null,
 primary key(platform,message_id)
);
alter table public.help_group_messages enable row level security;
revoke all on public.help_group_messages from public,anon,authenticated;
grant all on public.help_group_messages to service_role;
create function public.report_help_group(p_request bigint,p_platform text,p_message text,p_actor text,p_summary text)
returns boolean language plpgsql set search_path = '' as $$
declare r public.task_help_requests%rowtype;
begin
 select * into r from public.task_help_requests where request_no=p_request;
 if r.status<>'group_active' or p_actor not in (r.requester_code,r.selected_code)
  then raise exception 'Not a handoff participant'; end if;
 insert into public.help_group_messages values(p_platform,p_message,p_request,left(p_summary,1500)) on conflict do nothing;
 if not found then return false; end if;
 perform public.help_queue_admins(p_request,'update:'||p_platform||':'||p_message,
  left(format('HELP-%s update from %s: %s',p_request,p_actor,p_summary),2000));
 return true;
end;
$$;

revoke all on function public.help_queue_admins(bigint,text,text),
 public.help_transition(bigint,integer,text,text,jsonb,text,text),public.claim_help_notification(boolean),
 public.bind_help_group(uuid,uuid,text),
 public.finish_help_notification(uuid,uuid,text,text),public.report_help_group(bigint,text,text,text,text)
 from public,anon,authenticated;
grant execute on function public.help_queue_admins(bigint,text,text),
 public.help_transition(bigint,integer,text,text,jsonb,text,text),public.claim_help_notification(boolean),
 public.bind_help_group(uuid,uuid,text),
 public.finish_help_notification(uuid,uuid,text,text),public.report_help_group(bigint,text,text,text,text)
 to service_role;
notify pgrst,'reload schema';
commit;
