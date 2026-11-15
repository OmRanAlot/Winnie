-- Atomic, replay-safe task completion by the trusted messaging backend.
begin;

create table public.message_task_completions (
    platform text not null check (platform = 'imessage'),
    message_id text not null check (length(message_id) between 1 and 500),
    sender_id text not null,
    member_code text not null references public.members(code),
    request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
    task_id uuid not null references public.tasks(id),
    reply text not null,
    changed boolean not null,
    created_at timestamptz not null default now(),
    primary key (platform, message_id)
);

alter table public.message_task_completions enable row level security;
revoke all on public.message_task_completions from public, anon, authenticated;
grant select, insert on public.message_task_completions to service_role;

create function public.complete_task_from_message(
    p_platform text, p_message_id text, p_sender_id text, p_member_code text,
    p_request_hash text, p_task_id uuid, p_expected_updated_at timestamptz,
    p_expected_assignee_text text, p_semester_code text
) returns jsonb
language plpgsql set search_path = '' as $$
declare
    receipt public.message_task_completions%rowtype;
    task public.tasks%rowtype;
    result_reply text;
    did_change boolean;
begin
    if not exists (
        select 1 from public.member_identities i join public.members m on m.code = i.member_code
        where i.platform = p_platform and i.sender_id = p_sender_id
            and i.member_code = p_member_code and m.active
    ) then
        raise exception 'Messaging identity is not active';
    end if;
    -- Serialize identical provider events, including simultaneous deliveries.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_platform || ':' || p_message_id, 0)
    );
    select * into receipt from public.message_task_completions
        where platform = p_platform and message_id = p_message_id;
    if found then
        if receipt.sender_id <> p_sender_id or receipt.member_code <> p_member_code
            or receipt.request_hash <> p_request_hash then
            raise exception 'Message identity or payload changed';
        end if;
        return jsonb_build_object('reply', receipt.reply, 'changed', receipt.changed, 'replayed', true);
    end if;

    -- Ownership was resolved using verified aliases in Python. Lock and compare the
    -- original task version/assignment so that authorization cannot race a task edit.
    select * into task from public.tasks where id = p_task_id for update;
    if not found or task.semester_code is distinct from p_semester_code then
        raise exception 'Task is unavailable in this semester';
    end if;
    if task.updated_at is distinct from p_expected_updated_at
        or task.assignee_text is distinct from p_expected_assignee_text then
        raise exception 'Task changed; reload before completing';
    end if;
    did_change := task.status <> 'done';
    if did_change then
        update public.tasks set status = 'done' where id = task.id;
        result_reply := format('Marked "%s" (%s) done.', task.title, task.task_code);
    else
        result_reply := format('"%s" (%s) is already done.', task.title, task.task_code);
    end if;
    insert into public.message_task_completions (
        platform, message_id, sender_id, member_code, request_hash, task_id, reply, changed
    ) values (
        p_platform, p_message_id, p_sender_id, p_member_code, p_request_hash,
        task.id, result_reply, did_change
    );
    return jsonb_build_object('reply', result_reply, 'changed', did_change, 'replayed', false);
end;
$$;

revoke all on function public.complete_task_from_message(
    text, text, text, text, text, uuid, timestamptz, text, text
) from public, anon, authenticated;
grant execute on function public.complete_task_from_message(
    text, text, text, text, text, uuid, timestamptz, text, text
) to service_role;

notify pgrst, 'reload schema';
commit;
