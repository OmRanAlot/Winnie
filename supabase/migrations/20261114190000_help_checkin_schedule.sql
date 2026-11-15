-- Extend the existing outbox; do not rerun the original reminder migration.
begin;
alter table public.reminder_deliveries drop constraint reminder_deliveries_kind_check;
alter table public.reminder_deliveries add constraint reminder_deliveries_kind_check
    check (kind in ('fourteen_day','seven_day','five_day_help','three_day','previous_evening'));

create table public.task_help_requests (
    request_no bigint generated always as identity primary key,
    task_id uuid not null references public.tasks(id) on delete cascade,
    requester_code text not null references public.members(code),
    task_version timestamptz not null,
    status text not null default 'awaiting_recommendations'
        check (status in ('awaiting_recommendations','suggestions_ready','cancelled')),
    revision integer not null default 1,
    created_at timestamptz not null default now()
);
create unique index task_one_active_help_request_idx
    on public.task_help_requests(task_id,requester_code) where status not in ('cancelled','denied');

create table public.task_help_request_messages (
    platform text not null,
    message_id text not null check (length(message_id) between 1 and 500),
    sender_id text not null,
    requester_code text not null references public.members(code),
    request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
    request_no bigint not null references public.task_help_requests(request_no) on delete cascade,
    reply text not null,
    primary key(platform,message_id)
);
alter table public.task_help_requests enable row level security;
alter table public.task_help_request_messages enable row level security;
revoke all on public.task_help_requests, public.task_help_request_messages from public,anon,authenticated;
grant all on public.task_help_requests, public.task_help_request_messages to service_role;
grant usage,select on sequence public.task_help_requests_request_no_seq to service_role;

create function public.request_task_help(
    p_platform text,p_message_id text,p_sender_id text,p_member_code text,p_request_hash text,
    p_task_id uuid,p_expected_updated_at timestamptz,p_expected_assignee_text text,p_semester text
) returns jsonb language plpgsql set search_path = '' as $$
declare
    receipt public.task_help_request_messages%rowtype;
    task public.tasks%rowtype;
    request public.task_help_requests%rowtype;
    response text;
begin
    if not exists (select 1 from public.member_identities i join public.members m on m.code=i.member_code
        where i.platform=p_platform and i.sender_id=p_sender_id and i.member_code=p_member_code and m.active)
        then raise exception 'Unverified member'; end if;
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_platform || ':' || p_message_id,0));
    select * into receipt from public.task_help_request_messages where platform=p_platform and message_id=p_message_id;
    if found then
        if receipt.sender_id <> p_sender_id or receipt.requester_code <> p_member_code
            or receipt.request_hash <> p_request_hash then raise exception 'Message changed'; end if;
        return jsonb_build_object('reply',receipt.reply,'request_no',receipt.request_no,'replayed',true);
    end if;
    select * into task from public.tasks where id=p_task_id for update;
    if not found or task.status='done' or task.semester_code is distinct from p_semester
        or task.updated_at is distinct from p_expected_updated_at
        or task.assignee_text is distinct from p_expected_assignee_text
        then raise exception 'Task changed or unavailable'; end if;
    select * into request from public.task_help_requests where task_id=p_task_id
        and requester_code=p_member_code and status not in ('cancelled','denied') for update;
    if not found then
        insert into public.task_help_requests(task_id,requester_code,task_version)
        values (p_task_id,p_member_code,task.updated_at) returning * into request;
    end if;
    response := format('Saved help request HELP-%s for "%s" (%s). Ownership has not changed.',
        request.request_no,task.title,task.task_code);
    insert into public.task_help_request_messages(platform,message_id,sender_id,requester_code,request_hash,request_no,reply)
    values (p_platform,p_message_id,p_sender_id,p_member_code,p_request_hash,request.request_no,response);
    return jsonb_build_object('reply',response,'request_no',request.request_no,'replayed',false);
end;
$$;
revoke all on function public.request_task_help(text,text,text,text,text,uuid,timestamptz,text,text) from public,anon,authenticated;
grant execute on function public.request_task_help(text,text,text,text,text,uuid,timestamptz,text,text) to service_role;

create function public.invalidate_help_requests() returns trigger
language plpgsql set search_path = '' as $$
begin
    if new.status='done' or new.due_date is distinct from old.due_date
        or new.assignee_text is distinct from old.assignee_text then
        update public.task_help_requests set status='cancelled',revision=revision+1
        where task_id=new.id and status <> 'cancelled';
    end if;
    return new;
end;
$$;
revoke all on function public.invalidate_help_requests() from public,anon,authenticated;
create trigger invalidate_help_requests after update of status,due_date,assignee_text
    on public.tasks for each row execute function public.invalidate_help_requests();
notify pgrst, 'reload schema';
commit;
