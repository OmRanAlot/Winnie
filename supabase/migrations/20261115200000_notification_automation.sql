-- Request-driven automation: no migration sends messages or changes roster/contact data.
begin;
create function public.task_notification_recipients(t public.tasks) returns text[]
language plpgsql stable security definer set search_path='' as $$
declare interpretations jsonb;
begin
 if t.owner_code is not null then return array[t.owner_code]; end if;
 if trim(t.assignee_text)='' then return '{}'; end if;
 -- Whole verified aliases only. All co-owners must resolve; ambiguous parses fail closed.
 with recursive aliases as (
  select lower(trim(regexp_replace(alias,'\s+',' ','g'))) alias,member_code
   from public.member_aliases where semester_code=t.semester_code and trim(alias)<>''
 ), parse(rest,codes) as (
  select lower(trim(regexp_replace(t.assignee_text,'\s+',' ','g'))),array[]::text[]
  union
  select regexp_replace(regexp_replace(substr(p.rest,length(a.alias)+1),'^[ ,;&/|]+',''),'^and ','') ,p.codes||a.member_code
   from parse p join aliases a on left(p.rest,length(a.alias))=a.alias
   where length(p.rest)=length(a.alias) or substr(p.rest,length(a.alias)+1,1) ~ '[ ,;&/|]'
 ), resolved as (
  select distinct array(select distinct c from unnest(codes) c order by c) codes from parse where rest=''
 ) select jsonb_agg(to_jsonb(codes)) into interpretations from resolved;
 if jsonb_array_length(interpretations)=1 then
  return array(select jsonb_array_elements_text(interpretations->0));
 end if;
 return null;
end;
$$;
revoke all on function public.task_notification_recipients(public.tasks) from public,anon,authenticated;
grant execute on function public.task_notification_recipients(public.tasks) to service_role;

create table public.task_notifications (
 id uuid primary key default gen_random_uuid(),task_id uuid not null references public.tasks(id) on delete cascade,
 kind text not null check(kind in ('assignment','dependency','nudge','overdue')),
 event_key text not null,recipient_code text not null references public.members(code),
 owner_snapshot text,assignee_snapshot text not null,due_snapshot date,due_time_snapshot time,
 status text not null default 'pending' check(status in ('pending','sending','sent','uncertain','cancelled')),
 claim_token uuid,started_at timestamptz,provider_id text,created_at timestamptz not null default now(),
 expires_at timestamptz,unique(task_id,kind,event_key,recipient_code)
);
alter table public.task_notifications enable row level security;
revoke all on public.task_notifications from public,anon,authenticated;
grant all on public.task_notifications to service_role;
create index task_notifications_pending on public.task_notifications(status,created_at);

create function public.enqueue_task_notification(p_task uuid,p_kind text,p_key text,p_expires timestamptz default null)
returns integer language plpgsql security definer set search_path='' as $$
declare t public.tasks; codes text[]; inserted integer;
begin
 select * into t from public.tasks where id=p_task;
 if not found or t.status='done' then return 0; end if;
 codes:=public.task_notification_recipients(t);
 insert into public.task_notifications(task_id,kind,event_key,recipient_code,owner_snapshot,assignee_snapshot,due_snapshot,due_time_snapshot,expires_at)
  select t.id,p_kind,p_key,m.code,t.owner_code,t.assignee_text,t.due_date,t.due_time,p_expires
   from public.members m where m.active and m.code=any(codes)
  on conflict(task_id,kind,event_key,recipient_code) do update set
   owner_snapshot=excluded.owner_snapshot,assignee_snapshot=excluded.assignee_snapshot,
   due_snapshot=excluded.due_snapshot,due_time_snapshot=excluded.due_time_snapshot,
   status='pending',expires_at=excluded.expires_at
  where task_notifications.kind<>'nudge' and task_notifications.started_at is null
   and task_notifications.status in ('pending','cancelled') and
    (task_notifications.status='cancelled' or row(task_notifications.owner_snapshot,task_notifications.assignee_snapshot,task_notifications.due_snapshot,task_notifications.due_time_snapshot)
     is distinct from row(excluded.owner_snapshot,excluded.assignee_snapshot,excluded.due_snapshot,excluded.due_time_snapshot));
 get diagnostics inserted=row_count; return inserted;
end;
$$;
revoke all on function public.enqueue_task_notification(uuid,text,text,timestamptz) from public,anon,authenticated;
grant execute on function public.enqueue_task_notification(uuid,text,text,timestamptz) to service_role;

create function public.queue_dependency_ready(p_task uuid) returns integer
language plpgsql security definer set search_path='' as $$
declare fingerprint text;
begin
 if not exists(select 1 from public.task_dependencies where task_id=p_task)
  or exists(select 1 from public.task_dependencies d join public.tasks t on t.id=d.depends_on_id
   where d.task_id=p_task and t.status<>'done') then return 0; end if;
 select md5(string_agg(t.id::text||':'||coalesce(t.completed_at::text,'legacy'),',' order by t.id))
  into fingerprint from public.task_dependencies d join public.tasks t on t.id=d.depends_on_id where d.task_id=p_task;
 return public.enqueue_task_notification(p_task,'dependency',fingerprint);
end;
$$;
revoke all on function public.queue_dependency_ready(uuid) from public,anon,authenticated;
grant execute on function public.queue_dependency_ready(uuid) to service_role;

create function public.task_notification_events() returns trigger language plpgsql security definer set search_path='' as $$
declare child uuid;
begin
 if tg_op='INSERT' then
  -- Event-plan approval already has its own atomic assignment outbox.
  if new.source_plan_id is null then perform public.enqueue_task_notification(new.id,'assignment',new.updated_at::text); end if;
 elsif new.status='done' and old.status<>'done' then
  for child in select task_id from public.task_dependencies where depends_on_id=new.id loop
   perform public.queue_dependency_ready(child);
  end loop;
 elsif row(new.owner_code,new.assignee_text) is distinct from row(old.owner_code,old.assignee_text)
  and pg_trigger_depth()=1 then
  -- Nested approved handoffs send their dedicated outcome notices instead.
  perform public.enqueue_task_notification(new.id,'assignment',new.updated_at::text);
 end if;
 return new;
end;
$$;
revoke all on function public.task_notification_events() from public,anon,authenticated;
create trigger task_notification_events after insert or update of status,owner_code,assignee_text on public.tasks
 for each row execute function public.task_notification_events();

create function public.scan_task_notifications(p_semester text,p_timezone text default 'America/New_York',p_overdue boolean default true,p_now timestamptz default now())
returns jsonb language plpgsql security definer set search_path='' as $$
declare t public.tasks; local_now timestamp:=p_now at time zone p_timezone; ready integer:=0; overdue integer:=0;
begin
 for t in select * from public.tasks where semester_code=p_semester and status<>'done' loop
  -- Reconcile readiness too: concurrent prerequisite completions cannot lose a notification.
  ready:=ready+public.queue_dependency_ready(t.id);
  if p_overdue and extract(hour from local_now)>=9 and extract(hour from local_now)<20
   and t.due_date is not null and (t.due_date+coalesce(t.due_time,time '17:00'))<local_now then
   overdue:=overdue+public.enqueue_task_notification(t.id,'overdue',local_now::date::text,
    (local_now::date+1+time '00:00') at time zone p_timezone);
  end if;
 end loop;
 return jsonb_build_object('dependency_queued',ready,'overdue_queued',overdue);
end;
$$;
revoke all on function public.scan_task_notifications(text,text,boolean,timestamptz) from public,anon,authenticated;
grant execute on function public.scan_task_notifications(text,text,boolean,timestamptz) to service_role;

create function public.nudge_task(p_actor uuid,p_task uuid,p_semester text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare t public.tasks; eligible integer; inserted integer; key text:=(now() at time zone 'America/New_York')::date::text;
begin
 if not exists(select 1 from public.profiles p join public.members m on m.code=p.member_code
  join auth.users u on u.id=p.id where p.id=p_actor and p.is_admin and p.password_setup_complete
   and m.active and m.contact_consent and u.email_confirmed_at is not null
   and m.email=lower(trim(u.email)) and lower(trim(p.email))=m.email) then
  raise exception 'Administrator required' using errcode='42501'; end if;
 select * into t from public.tasks where id=p_task for share;
 if not found then raise exception 'Task not found' using errcode='P0002'; end if;
 if t.status='done' or t.semester_code is distinct from p_semester then
  raise exception 'Only unfinished active-semester tasks can be nudged' using errcode='22023'; end if;
 select count(*) into eligible from public.member_identities i join public.members m on m.code=i.member_code
  where m.code=any(public.task_notification_recipients(t)) and m.active and m.contact_consent
   and i.platform='imessage' and i.reminders_enabled;
 if eligible=0 then raise exception 'No opted-in messaging recipient is linked to this assignment' using errcode='22023'; end if;
 inserted:=public.enqueue_task_notification(t.id,'nudge',key,now()+interval '24 hours');
 return jsonb_build_object('queued',inserted,'already_requested',inserted=0);
end;
$$;
revoke all on function public.nudge_task(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.nudge_task(uuid,uuid,text) to service_role;

create function public.claim_task_notification(p_semester text,p_timezone text default 'America/New_York',p_now timestamptz default now())
returns jsonb language plpgsql security definer set search_path='' as $$
declare n public.task_notifications; t public.tasks; token uuid; destination text; body text; local_hour integer:=extract(hour from p_now at time zone p_timezone);
begin
 update public.task_notifications set status='uncertain' where status='sending' and started_at<p_now-interval '2 minutes';
 update public.task_notifications notice set status='cancelled' where status='pending' and (
  (expires_at is not null and expires_at<=p_now) or not exists(select 1 from public.tasks x where x.id=notice.task_id
   and x.status<>'done' and x.semester_code=p_semester and row(x.owner_code,x.assignee_text,x.due_date,x.due_time)
    is not distinct from row(notice.owner_snapshot,notice.assignee_snapshot,notice.due_snapshot,notice.due_time_snapshot)
   and notice.recipient_code=any(public.task_notification_recipients(x)))
  or (kind='dependency' and (not exists(select 1 from public.task_dependencies where task_id=notice.task_id)
   or exists(select 1 from public.task_dependencies d join public.tasks parent on parent.id=d.depends_on_id
    where d.task_id=notice.task_id and parent.status<>'done')
   or event_key is distinct from (select md5(string_agg(parent.id::text||':'||coalesce(parent.completed_at::text,'legacy'),',' order by parent.id))
    from public.task_dependencies d join public.tasks parent on parent.id=d.depends_on_id where d.task_id=notice.task_id))));
 if local_hour<9 or local_hour>=20 then return null; end if;
 select candidate.* into n from public.task_notifications candidate where candidate.status='pending' and exists(
  select 1 from public.members m join public.member_identities i on i.member_code=m.code where m.code=candidate.recipient_code
   and m.active and m.contact_consent and i.platform='imessage' and i.reminders_enabled)
  order by candidate.created_at,candidate.id for update skip locked limit 1;
 if not found then return null; end if;
 select * into strict t from public.tasks where id=n.task_id;
 select sender_id into destination from public.member_identities where member_code=n.recipient_code and platform='imessage' and reminders_enabled;
 body:=case n.kind when 'assignment' then 'New assignment: ' when 'dependency' then 'Prerequisites complete; your task is ready: '
  when 'overdue' then 'Overdue reminder: ' else 'Admin nudge: ' end || t.title||' ('||t.task_code||')'||
  case when t.due_date is not null then ', due '||t.due_date::text||coalesce(' '||left(t.due_time::text,5)||' ET','') else '' end||
  '. Reply done '||t.task_code||' when finished, or help '||t.task_code||' for replacement suggestions.';
 token:=gen_random_uuid(); update public.task_notifications set status='sending',claim_token=token,started_at=p_now where id=n.id;
 return jsonb_build_object('id',n.id,'claim_token',token,'recipient',destination,'text',body);
end;
$$;
create function public.finish_task_notification(p_id uuid,p_token uuid,p_outcome text,p_provider_id text) returns text
language plpgsql security definer set search_path='' as $$
declare n public.task_notifications;
begin
 select * into n from public.task_notifications where id=p_id for update;
 if not found or n.claim_token is distinct from p_token then return 'ignored'; end if;
 if n.status='sent' then return 'sent'; end if;
 if n.status<>'sending' or p_outcome not in ('sent','uncertain') then return 'ignored'; end if;
 if p_outcome='sent' and nullif(p_provider_id,'') is null then raise exception 'Provider receipt required'; end if;
 update public.task_notifications set status=p_outcome,provider_id=p_provider_id where id=p_id;
 return p_outcome;
end;
$$;
revoke all on function public.claim_task_notification(text,text,timestamptz) from public,anon,authenticated;
revoke all on function public.finish_task_notification(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.claim_task_notification(text,text,timestamptz) to service_role;
grant execute on function public.finish_task_notification(uuid,uuid,text,text) to service_role;

-- Revalidate all modern ownership/consent rules just before the existing reminder sender begins.
alter function public.begin_deadline_reminder(uuid,uuid,timestamptz,boolean) rename to begin_deadline_reminder_v1;
revoke all on function public.begin_deadline_reminder_v1(uuid,uuid,timestamptz,boolean) from public,anon,authenticated,service_role;
create function public.begin_deadline_reminder(p_id uuid,p_token uuid,p_now timestamptz,p_assignment_verified boolean)
returns jsonb language plpgsql security definer set search_path='' as $$
declare d public.reminder_deliveries; t public.tasks; allowed boolean:=false;
begin
 select * into d from public.reminder_deliveries where id=p_id;
 select * into t from public.tasks where id=d.task_id for share;
 allowed:=p_assignment_verified and d.member_code=any(public.task_notification_recipients(t))
  and t.reminder_schedule_started_at<=d.scheduled_at and exists(select 1 from public.members where code=d.member_code and active and contact_consent);
 return public.begin_deadline_reminder_v1(p_id,p_token,p_now,coalesce(allowed,false));
end;
$$;
revoke all on function public.begin_deadline_reminder(uuid,uuid,timestamptz,boolean) from public,anon,authenticated;
grant execute on function public.begin_deadline_reminder(uuid,uuid,timestamptz,boolean) to service_role;
create or replace function public.invalidate_task_reminders() returns trigger language plpgsql set search_path='' as $$
begin
 if row(new.due_date,new.due_time,new.owner_code,new.assignee_text) is distinct from row(old.due_date,old.due_time,old.owner_code,old.assignee_text) then
  new.reminder_schedule_started_at:=now();
 end if;
 if new.status='done' or row(new.due_date,new.due_time,new.owner_code,new.assignee_text) is distinct from row(old.due_date,old.due_time,old.owner_code,old.assignee_text) then
  update public.reminder_deliveries set status='cancelled',reason='task_changed' where task_id=new.id and status in ('pending','claimed','failed');
 end if;
 return new;
end;
$$;
drop trigger invalidate_task_reminders on public.tasks;
create trigger invalidate_task_reminders before update of status,due_date,due_time,owner_code,assignee_text on public.tasks
 for each row execute function public.invalidate_task_reminders();

create table public.automation_jobs (
 key text primary key,status text not null check(status in ('running','succeeded','conflict','failed')),
 claim_token uuid not null,started_at timestamptz not null,finished_at timestamptz,summary jsonb not null default '{}'
);
alter table public.automation_jobs enable row level security;
revoke all on public.automation_jobs from public,anon,authenticated;
grant all on public.automation_jobs to service_role;
create function public.claim_automation_job(p_key text) returns uuid language plpgsql security definer set search_path='' as $$
declare token uuid:=gen_random_uuid(); result uuid;
begin
 insert into public.automation_jobs as j(key,status,claim_token,started_at) values(p_key,'running',token,now())
  on conflict(key) do update set status='running',claim_token=token,started_at=now(),finished_at=null,summary='{}'
   where j.status<>'running' or j.started_at<now()-interval '5 minutes' returning claim_token into result;
 return result;
end;
$$;
create function public.finish_automation_job(p_key text,p_token uuid,p_status text,p_summary jsonb) returns boolean
language plpgsql security definer set search_path='' as $$
begin
 if p_status not in ('succeeded','conflict','failed') then raise exception 'Invalid job outcome'; end if;
 update public.automation_jobs set status=p_status,summary=p_summary,finished_at=now() where key=p_key and claim_token=p_token and status='running';
 return found;
end;
$$;
revoke all on function public.claim_automation_job(text) from public,anon,authenticated;
revoke all on function public.finish_automation_job(text,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.claim_automation_job(text) to service_role;
grant execute on function public.finish_automation_job(text,uuid,text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
