-- Durable source baselines and atomic Google tracker imports. Server-only access.
begin;
create table public.sheet_sync_state (
    spreadsheet_id text not null,
    source_task_id text not null,
    task_id uuid not null references public.tasks(id) on delete cascade,
    source_values jsonb not null,
    version bigint not null default 1,
    primary key (spreadsheet_id, source_task_id)
);
create table public.sheet_sync_runs (
    id bigint generated always as identity primary key,
    source_key text not null,
    created_at timestamptz not null default now(),
    summary jsonb not null
);
create index sheet_sync_runs_source_idx on public.sheet_sync_runs(source_key, created_at desc);
alter table public.sheet_sync_state enable row level security;
alter table public.sheet_sync_runs enable row level security;
revoke all on public.sheet_sync_state, public.sheet_sync_runs from anon, authenticated;
grant all on public.sheet_sync_state, public.sheet_sync_runs to service_role;
grant usage, select on sequence public.sheet_sync_runs_id_seq to service_role;

create function public.apply_sheet_sync(plan jsonb) returns jsonb
language plpgsql set search_path = public as $$
declare
    op jsonb; existing tasks%rowtype; incoming tasks%rowtype;
    state sheet_sync_state%rowtype; saved_id uuid; changes jsonb;
begin
    if jsonb_array_length(plan->'conflicts') <> 0 then
        raise exception 'Unresolved sync conflicts' using errcode = '22023';
    end if;
    -- Serialize workers for one workbook, including requests for different monthly tabs.
    perform pg_advisory_xact_lock(hashtextextended(plan->>'spreadsheet_id', 0));
    if exists (select 1 from tasks where source_spreadsheet_id = plan->>'spreadsheet_id'
        and semester_code = plan->>'semester_code'
        and project_name is not distinct from plan->>'project_name'
        and snapshot_month is not null
        and (plan->>'snapshot_month' is null or snapshot_month > plan->>'snapshot_month')) then
        raise exception 'A later tracker snapshot exists' using errcode = '40001';
    end if;
    for op in select * from jsonb_array_elements(plan->'operations') loop
        select * into state from sheet_sync_state
            where spreadsheet_id = plan->>'spreadsheet_id'
            and source_task_id = op->>'source_task_id' for update;
        if state.version is distinct from (op->>'expected_state_version')::bigint then
            raise exception 'Sync baseline changed' using errcode = '40001';
        end if;
        select * into existing from tasks
            where source_spreadsheet_id = plan->>'spreadsheet_id'
            and source_task_id = op->>'source_task_id' for update;
        if op->>'action' = 'insert' then
            if existing.id is not null then
                raise exception 'Task appeared after preview' using errcode = '40001';
            end if;
            incoming := jsonb_populate_record(null::tasks, op->'values');
            if incoming.source_spreadsheet_id is distinct from plan->>'spreadsheet_id'
                or incoming.source_task_id is distinct from op->>'source_task_id'
                or incoming.semester_code is distinct from plan->>'semester_code'
                or incoming.source is distinct from 'sheet' then
                raise exception 'Invalid source identity' using errcode = '22023';
            end if;
            insert into tasks(title,description,month_code,semester_code,source,status,priority,
                assignee_text,deadline_text,due_date,event_tag,category,project_name,snapshot_month,
                source_spreadsheet_id,source_task_id,source_tab_id,source_tab_name)
            values(incoming.title,incoming.description,incoming.month_code,incoming.semester_code,
                'sheet',incoming.status,incoming.priority,incoming.assignee_text,incoming.deadline_text,
                incoming.due_date,incoming.event_tag,incoming.category,incoming.project_name,
                incoming.snapshot_month,incoming.source_spreadsheet_id,incoming.source_task_id,
                incoming.source_tab_id,incoming.source_tab_name)
            returning id into saved_id;
        else
            if existing.id is null or existing.id is distinct from (op->>'id')::uuid
                or existing.updated_at is distinct from (op->>'expected_updated_at')::timestamptz
                or existing.semester_code is distinct from plan->>'semester_code'
                or existing.source is distinct from 'sheet' then
                raise exception 'Task changed after preview' using errcode = '40001';
            end if;
            saved_id := existing.id;
            if op->>'action' = 'update' then
                changes := op->'values';
                incoming := jsonb_populate_record(existing, changes);
                -- Explicit field allowlist: ownership, notes and task identity remain untouched.
                update tasks set title=incoming.title, description=incoming.description,
                    status=incoming.status, priority=incoming.priority,
                    assignee_text=incoming.assignee_text, deadline_text=incoming.deadline_text,
                    due_date=incoming.due_date, event_tag=incoming.event_tag,
                    category=incoming.category, project_name=incoming.project_name,
                    snapshot_month=incoming.snapshot_month, source_tab_id=incoming.source_tab_id,
                    source_tab_name=incoming.source_tab_name where id=saved_id;
            elsif op->>'action' <> 'unchanged' then
                raise exception 'Invalid sync action' using errcode = '22023';
            end if;
        end if;
        insert into sheet_sync_state(spreadsheet_id,source_task_id,task_id,source_values)
        values(plan->>'spreadsheet_id',op->>'source_task_id',saved_id,op->'source_values')
        on conflict (spreadsheet_id,source_task_id) do update
            set source_values=excluded.source_values, task_id=excluded.task_id,
                version=sheet_sync_state.version+1;
    end loop;
    insert into sheet_sync_runs(source_key,summary) values(plan->>'source_key',plan->'summary');
    return plan->'summary';
end;
$$;
revoke all on function public.apply_sheet_sync(jsonb) from public, anon, authenticated;
grant execute on function public.apply_sheet_sync(jsonb) to service_role;
notify pgrst, 'reload schema';
commit;
