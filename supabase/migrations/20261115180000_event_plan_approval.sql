-- Shared administrator drafts; approval is one transaction with tasks, edges and outbox.
begin;
create table public.event_plans (
 id uuid primary key default gen_random_uuid(),
 payload jsonb not null check(jsonb_typeof(payload)='object'),
 semester_code text not null check(semester_code ~ '^(spring|summer|fall|winter)-[0-9]{4}$'),
 revision integer not null default 1,
 status text not null default 'draft' check(status in ('draft','approved','rejected')),
 created_by uuid not null references public.profiles(id),
 reviewed_by uuid references public.profiles(id),
 review_note text not null default '', reviewed_at timestamptz,
 activated_task_ids uuid[] not null default '{}',
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
alter table public.event_plans enable row level security;
revoke all on public.event_plans from public,anon,authenticated;
grant all on public.event_plans to service_role;
create table public.event_plan_reviews (
 plan_id uuid not null references public.event_plans(id), revision integer not null,
 decision text not null check(decision in ('approved','rejected')),
 reviewer_id uuid not null references public.profiles(id), note text not null,
 payload jsonb not null, reviewed_at timestamptz not null default now(),
 primary key(plan_id,revision)
);
alter table public.event_plan_reviews enable row level security;
revoke all on public.event_plan_reviews from public,anon,authenticated;
grant select,insert on public.event_plan_reviews to service_role;
alter table public.tasks add column source_plan_id uuid references public.event_plans(id),
 add column plan_task_key text;
create unique index tasks_plan_task_key on public.tasks(source_plan_id,plan_task_key);

create table public.event_plan_notifications (
 id uuid primary key default gen_random_uuid(),
 plan_id uuid not null references public.event_plans(id),
 task_id uuid not null references public.tasks(id) on delete cascade,
 recipient_code text not null references public.members(code),
 body text not null, status text not null default 'pending'
 check(status in ('pending','sending','sent','uncertain','cancelled')),
 claim_token uuid, started_at timestamptz, provider_id text,
 unique(plan_id,task_id,recipient_code)
);
alter table public.event_plan_notifications enable row level security;
revoke all on public.event_plan_notifications from public,anon,authenticated;
grant all on public.event_plan_notifications to service_role;

create function public.manage_event_plan(p_actor uuid,p_action text,p_id uuid default null,
 p_revision integer default null,p_payload jsonb default '{}') returns jsonb
language plpgsql security definer set search_path='' as $$
declare plan public.event_plans; item jsonb; dep text; created public.tasks;
 ids jsonb := '{}'; task_ids uuid[] := '{}'; result jsonb;
begin
 -- A server-supplied actor must still have current, verified roster access and admin rights.
 if not exists(select 1 from public.profiles p join public.members m on m.code=p.member_code
  join auth.users u on u.id=p.id where p.id=p_actor and p.is_admin and p.password_setup_complete
  and u.email_confirmed_at is not null and m.active and m.contact_consent
  and m.email=lower(trim(u.email)) and lower(trim(p.email))=m.email) then
  raise exception 'Administrator required' using errcode='42501';
 end if;
 if p_action='list' then
  select coalesce(jsonb_agg(to_jsonb(e) order by e.updated_at desc,e.id),'[]') into result
   from public.event_plans e;
  return result;
 end if;
 if p_action='create' then
  insert into public.event_plans(payload,semester_code,created_by)
   values(p_payload-'semester_code',p_payload->>'semester_code',p_actor) returning * into plan;
  return to_jsonb(plan);
 end if;
 select * into plan from public.event_plans where id=p_id for update;
 if not found then raise exception 'Plan not found' using errcode='P0002'; end if;
 if p_action='get' then return to_jsonb(plan); end if;
 if p_revision is null or p_revision<>plan.revision then
  raise exception 'Stale revision' using errcode='40001';
 end if;
 -- Retrying the exact approved/rejected revision returns its committed outcome.
 if p_action=plan.status and p_action in ('approved','rejected') then return to_jsonb(plan); end if;
 if plan.status='approved' or (plan.status='rejected' and p_action<>'update') then
  raise exception 'Plan already decided' using errcode='40001';
 end if;
 if p_action='update' then
  update public.event_plans set payload=p_payload,revision=revision+1,status='draft',
   reviewed_by=null,reviewed_at=null,review_note='',updated_at=now()
   where id=p_id returning * into plan;
  return to_jsonb(plan);
 end if;
 if p_action not in ('approved','rejected') then
  raise exception 'Invalid action' using errcode='22023';
 end if;
 if p_action='approved' then
  if jsonb_typeof(plan.payload->'tasks') is distinct from 'array'
   or jsonb_array_length(plan.payload->'tasks') not between 1 and 80 then
   raise exception 'Structured tasks required' using errcode='22023';
  end if;
  -- Lock selected owners before checking activity, preventing concurrent deactivation.
  perform 1 from public.members m where m.code in
   (select t->>'owner_code' from jsonb_array_elements(plan.payload->'tasks') t) for share;
  if (select count(*)<>count(distinct t->>'id') from jsonb_array_elements(plan.payload->'tasks') t)
   or exists(select 1 from jsonb_array_elements(plan.payload->'tasks') t
    where nullif(trim(t->>'id'),'') is null or nullif(trim(t->>'title'),'') is null
     or nullif(t->>'due_date','') is null
     or not exists(select 1 from public.members m where m.code=t->>'owner_code' and m.active)) then
   raise exception 'Tasks require unique IDs, owners and dates' using errcode='22023';
  end if;
  if exists(select 1 from jsonb_array_elements(plan.payload->'tasks') t,
    jsonb_array_elements_text(t->'dependency_ids') d
    where not exists(select 1 from jsonb_array_elements(plan.payload->'tasks') parent
      where parent->>'id'=d and (parent->>'due_date')::date<=(t->>'due_date')::date)) then
   raise exception 'Invalid dependency/date' using errcode='22023';
  end if;
  if exists(with recursive edges as (
    select t->>'id' child,d parent from jsonb_array_elements(plan.payload->'tasks') t,
     jsonb_array_elements_text(t->'dependency_ids') d
   ), walk(node,path,cycle) as (
    select child,array[child],false from edges
    union all select e.parent,w.path||e.parent,e.parent=any(w.path)
     from walk w join edges e on e.child=w.node where not w.cycle
   ) select 1 from walk where cycle) then
   raise exception 'Dependency cycle' using errcode='22023';
  end if;
  for item in select * from jsonb_array_elements(plan.payload->'tasks') loop
   insert into public.tasks(title,description,month_code,semester_code,owner_code,assignee_text,
     due_date,due_time,event_tag,project_name,source_reference,source_plan_id,plan_task_key)
    values(item->>'title',coalesce(item->>'description',''),
     to_char((item->>'due_date')::date,'YYYY-MM'),plan.semester_code,item->>'owner_code',
     (select display_name from public.members where code=item->>'owner_code'),
     (item->>'due_date')::date,nullif(item->>'due_time','')::time,
     left(plan.payload->>'event_name',100),plan.payload->>'event_name',
     'event-plan:'||plan.id::text,plan.id,item->>'id') returning * into created;
   ids:=ids||jsonb_build_object(item->>'id',created.id);
   task_ids:=array_append(task_ids,created.id);
   insert into public.event_plan_notifications(plan_id,task_id,recipient_code,body)
    values(plan.id,created.id,created.owner_code,
     'New assignment: '||created.title||' ('||created.task_code||') for '||
     (plan.payload->>'event_name')||', due '||created.due_date::text||'. Reply done '||created.task_code||' or help '||created.task_code||'.');
  end loop;
  for item in select * from jsonb_array_elements(plan.payload->'tasks') loop
   for dep in select * from jsonb_array_elements_text(item->'dependency_ids') loop
    insert into public.task_dependencies(task_id,depends_on_id)
     values((ids->>(item->>'id'))::uuid,(ids->>dep)::uuid) on conflict do nothing;
   end loop;
  end loop;
 end if;
 insert into public.event_plan_reviews(plan_id,revision,decision,reviewer_id,note,payload)
  values(plan.id,plan.revision,p_action,p_actor,coalesce(p_payload->>'note',''),plan.payload);
 update public.event_plans set status=p_action,reviewed_by=p_actor,reviewed_at=now(),
  review_note=coalesce(p_payload->>'note',''),activated_task_ids=task_ids,updated_at=now()
  where id=p_id returning * into plan;
 return to_jsonb(plan);
end;
$$;
revoke all on function public.manage_event_plan(uuid,text,uuid,integer,jsonb) from public,anon,authenticated;
grant execute on function public.manage_event_plan(uuid,text,uuid,integer,jsonb) to service_role;

create function public.claim_event_plan_notification() returns jsonb
language plpgsql security definer set search_path='' as $$
declare n public.event_plan_notifications; token uuid; destination text;
begin
 update public.event_plan_notifications set status='uncertain'
  where status='sending' and started_at<now()-interval '2 minutes';
 update public.event_plan_notifications notice set status='cancelled' from public.tasks t
  where notice.task_id=t.id and notice.status='pending' and (t.status='done' or t.owner_code is distinct from notice.recipient_code);
 select n1.* into n from public.event_plan_notifications n1 where n1.status='pending' and exists(
  select 1 from public.member_identities i join public.members m on m.code=i.member_code
   where m.code=n1.recipient_code and m.active and m.contact_consent
    and i.platform='imessage' and i.reminders_enabled)
  order by n1.id for update skip locked limit 1;
 if not found then return null; end if;
 select sender_id into destination from public.member_identities where member_code=n.recipient_code
  and platform='imessage' and reminders_enabled order by sender_id limit 1;
 token:=gen_random_uuid();
 update public.event_plan_notifications set status='sending',claim_token=token,started_at=now() where id=n.id;
 return jsonb_build_object('id',n.id,'claim_token',token,'recipient',destination,'text',n.body);
end;
$$;
create function public.finish_event_plan_notification(p_id uuid,p_token uuid,p_outcome text,p_provider_id text) returns text
language plpgsql security definer set search_path='' as $$
declare n public.event_plan_notifications;
begin
 select * into n from public.event_plan_notifications where id=p_id for update;
 if not found then return 'not_found'; end if;
 if p_outcome not in ('sent','uncertain') or (p_outcome='sent' and nullif(p_provider_id,'') is null) then
  raise exception 'Invalid notification result'; end if;
 if n.claim_token is distinct from p_token then return 'ignored'; end if;
 if n.status='sent' then return 'sent'; end if;
 if n.status<>'sending' then return 'ignored'; end if;
 update public.event_plan_notifications set status=p_outcome,provider_id=p_provider_id where id=p_id;
 return p_outcome;
end;
$$;
revoke all on function public.claim_event_plan_notification() from public,anon,authenticated;
revoke all on function public.finish_event_plan_notification(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.claim_event_plan_notification() to service_role;
grant execute on function public.finish_event_plan_notification(uuid,uuid,text,text) to service_role;
notify pgrst,'reload schema';
commit;
