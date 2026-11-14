-- Persistent reminder schedule/outbox. Installation never sends messages.
begin;

alter table public.member_identities add column reminders_enabled boolean not null default false;
create unique index member_one_reminder_destination_idx on public.member_identities(member_code)
    where reminders_enabled;

alter table public.tasks add column reminder_schedule_started_at timestamptz;
update public.tasks set reminder_schedule_started_at = created_at;
alter table public.tasks alter column reminder_schedule_started_at set default now();
alter table public.tasks alter column reminder_schedule_started_at set not null;

create table public.reminder_deliveries (
    id uuid primary key default gen_random_uuid(),
    task_id uuid not null references public.tasks(id) on delete cascade,
    member_code text not null references public.members(code),
    due_date date not null,
    kind text not null check (kind in ('seven_day','three_day','previous_evening')),
    transport text not null check (transport in ('mock','photon')),
    scheduled_at timestamptz not null,
    expires_at timestamptz not null check (expires_at > scheduled_at),
    sender_id text not null,
    assignee_snapshot text not null,
    body text not null check (length(body) between 1 and 2000),
    status text not null default 'pending' check (
        status in ('pending','claimed','sending','sent','mock_sent','cancelled','uncertain','failed')
    ),
    attempts integer not null default 0,
    claim_token uuid,
    lease_until timestamptz,
    provider_started_at timestamptz,
    provider_message_id text,
    reason text,
    created_at timestamptz not null default now(),
    sent_at timestamptz,
    unique(task_id, member_code, due_date, kind, transport)
);
create index reminders_pending_idx on public.reminder_deliveries(status,scheduled_at);
alter table public.reminder_deliveries enable row level security;
revoke all on public.reminder_deliveries from public, anon, authenticated;
grant all on public.reminder_deliveries to service_role;

create function public.invalidate_task_reminders() returns trigger
language plpgsql set search_path = '' as $$
begin
    if new.due_date is distinct from old.due_date
        or new.assignee_text is distinct from old.assignee_text then
        new.reminder_schedule_started_at := now();
    end if;
    if new.status = 'done' or new.due_date is distinct from old.due_date
        or new.assignee_text is distinct from old.assignee_text then
        update public.reminder_deliveries set status='cancelled', reason='task_changed'
        where task_id=new.id and status in ('pending','claimed','failed');
    end if;
    return new;
end;
$$;
revoke all on function public.invalidate_task_reminders() from public, anon, authenticated;
create trigger invalidate_task_reminders before update of status,due_date,assignee_text
    on public.tasks for each row execute function public.invalidate_task_reminders();

create function public.queue_deadline_reminder(
    p_task_id uuid, p_member_code text, p_due_date date, p_kind text, p_transport text,
    p_scheduled_at timestamptz, p_expires_at timestamptz, p_sender_id text,
    p_assignee_snapshot text, p_body text, p_now timestamptz
) returns uuid language plpgsql set search_path = '' as $$
declare result uuid;
begin
    if not exists (select 1 from public.tasks t where t.id=p_task_id
        and t.status <> 'done' and t.due_date=p_due_date
        and t.assignee_text=p_assignee_snapshot
        and t.reminder_schedule_started_at <= p_scheduled_at)
        or not exists (select 1 from public.member_identities i join public.members m
            on m.code=i.member_code where i.member_code=p_member_code and m.active
            and i.platform='imessage' and i.sender_id=p_sender_id and i.reminders_enabled)
        or p_scheduled_at > p_now or p_expires_at <= p_now then
        return null;
    end if;
    insert into public.reminder_deliveries as d (
        task_id,member_code,due_date,kind,transport,scheduled_at,expires_at,
        sender_id,assignee_snapshot,body
    ) values (p_task_id,p_member_code,p_due_date,p_kind,p_transport,p_scheduled_at,p_expires_at,
        p_sender_id,p_assignee_snapshot,p_body)
    on conflict (task_id,member_code,due_date,kind,transport) do update set
        body=excluded.body, sender_id=excluded.sender_id, assignee_snapshot=excluded.assignee_snapshot,
        scheduled_at=excluded.scheduled_at, expires_at=excluded.expires_at,
        status=case when d.status='cancelled' then 'pending' else d.status end,
        attempts=case when d.status='cancelled' then 0 else d.attempts end,
        reason=null
    where d.status='pending' or (d.status='cancelled' and d.provider_started_at is null)
    returning id into result;
    return result;
end;
$$;

create function public.claim_deadline_reminder(p_transport text,p_now timestamptz)
returns jsonb language plpgsql set search_path = '' as $$
declare item public.reminder_deliveries%rowtype;
begin
    -- No sending row is automatically retried, including after process crashes.
    update public.reminder_deliveries set status='uncertain',reason='send_lease_expired'
        where status='sending' and lease_until <= p_now;
    update public.reminder_deliveries set status='failed',reason='claim_retries_exhausted'
        where status='claimed' and lease_until <= p_now and attempts >= 3;
    update public.reminder_deliveries d set status='cancelled',reason='obsolete'
    where status in ('pending','claimed','failed') and (
        expires_at <= p_now or not exists (select 1 from public.tasks t
            where t.id=d.task_id and t.status <> 'done' and t.due_date=d.due_date
                and t.assignee_text=d.assignee_snapshot)
        or not exists (select 1 from public.member_identities i join public.members m
            on m.code=i.member_code where i.member_code=d.member_code and m.active
            and i.platform='imessage' and i.sender_id=d.sender_id and i.reminders_enabled)
    );
    select * into item from public.reminder_deliveries
    where transport=p_transport and scheduled_at <= p_now and expires_at > p_now
        and attempts < 3 and (status='pending' or (status='claimed' and lease_until <= p_now))
    order by scheduled_at,id for update skip locked limit 1;
    if not found then return null; end if;
    update public.reminder_deliveries set status='claimed',attempts=attempts+1,
        claim_token=gen_random_uuid(),lease_until=p_now+interval '60 seconds'
    where id=item.id returning * into item;
    return to_jsonb(item);
end;
$$;

create function public.begin_deadline_reminder(p_id uuid,p_token uuid,p_now timestamptz,
    p_assignment_verified boolean)
returns jsonb language plpgsql set search_path = '' as $$
declare item public.reminder_deliveries%rowtype; target_task uuid;
begin
    -- Take task locks before delivery locks, matching the task-update trigger order.
    select task_id into target_task from public.reminder_deliveries where id=p_id;
    perform 1 from public.tasks where id=target_task for share;
    select * into item from public.reminder_deliveries where id=p_id for update;
    if not found or item.claim_token is distinct from p_token then return null; end if;
    if item.status <> 'claimed' or item.lease_until <= p_now then return null; end if;
    if not p_assignment_verified or item.expires_at <= p_now
        or not exists (select 1 from public.tasks t where t.id=item.task_id
            and t.status <> 'done' and t.due_date=item.due_date
            and t.assignee_text=item.assignee_snapshot)
        or not exists (select 1 from public.member_identities i join public.members m
            on m.code=i.member_code where m.active and i.member_code=item.member_code
            and i.platform='imessage' and i.sender_id=item.sender_id and i.reminders_enabled) then
        update public.reminder_deliveries set status='cancelled',reason='authorization_changed' where id=p_id;
        return null;
    end if;
    update public.reminder_deliveries set status='sending',provider_started_at=p_now,
        lease_until=p_now+interval '120 seconds'
    where id=p_id returning * into item;
    return to_jsonb(item);
end;
$$;

create function public.finish_deadline_reminder(
    p_id uuid,p_token uuid,p_outcome text,p_provider_id text,p_now timestamptz
) returns text language plpgsql set search_path = '' as $$
declare item public.reminder_deliveries%rowtype;
begin
    select * into item from public.reminder_deliveries where id=p_id for update;
    if not found or item.claim_token is distinct from p_token then
        raise exception 'Invalid delivery claim';
    end if;
    if item.status in ('sent','mock_sent') then return item.status; end if;
    if item.status not in ('sending','uncertain') or p_outcome not in ('sent','mock_sent','uncertain')
        or (p_outcome='sent' and (item.transport <> 'photon' or coalesce(p_provider_id,'')=''))
        or (p_outcome='mock_sent' and item.transport <> 'mock') then
        raise exception 'Invalid delivery result';
    end if;
    update public.reminder_deliveries set status=p_outcome,
        provider_message_id=p_provider_id,
        sent_at=case when p_outcome in ('sent','mock_sent') then p_now else null end,
        reason=case when p_outcome='uncertain' then 'provider_outcome_unknown' else null end
    where id=p_id;
    return p_outcome;
end;
$$;

revoke all on function public.queue_deadline_reminder(uuid,text,date,text,text,timestamptz,timestamptz,text,text,text,timestamptz) from public,anon,authenticated;
revoke all on function public.claim_deadline_reminder(text,timestamptz) from public,anon,authenticated;
revoke all on function public.begin_deadline_reminder(uuid,uuid,timestamptz,boolean) from public,anon,authenticated;
revoke all on function public.finish_deadline_reminder(uuid,uuid,text,text,timestamptz) from public,anon,authenticated;
grant execute on function public.queue_deadline_reminder(uuid,text,date,text,text,timestamptz,timestamptz,text,text,text,timestamptz) to service_role;
grant execute on function public.claim_deadline_reminder(text,timestamptz) to service_role;
grant execute on function public.begin_deadline_reminder(uuid,uuid,timestamptz,boolean) to service_role;
grant execute on function public.finish_deadline_reminder(uuid,uuid,text,text,timestamptz) to service_role;

notify pgrst, 'reload schema';
commit;
