-- Attendance is a roster-linked set, saved atomically through server-only functions.
begin;
alter table public.meetings add column attendance_recorded_at timestamptz;
create table public.meeting_attendance (
    meeting_id bigint not null references public.meetings(id) on delete cascade,
    member_code text not null references public.members(code),
    primary key (meeting_id, member_code)
);
alter table public.meeting_attendance enable row level security;
revoke all on public.meeting_attendance from anon, authenticated;
grant all on public.meeting_attendance to service_role;

create function public.save_meeting_attendance(meeting bigint, attendees text[])
returns void language plpgsql set search_path = public as $$
begin
    perform 1 from meetings where id = meeting for update;
    if not found then raise exception 'Meeting not found' using errcode = 'P0002'; end if;
    if attendees is null or exists (
        select 1 from unnest(attendees) a(code)
        left join members m on m.code = a.code
        where m.code is null or (not m.active and not exists (
            select 1 from meeting_attendance old
            where old.meeting_id = meeting and old.member_code = a.code
        ))
    ) then raise exception 'Select valid board members' using errcode = '22023'; end if;
    delete from meeting_attendance where meeting_id = meeting;
    insert into meeting_attendance(meeting_id, member_code)
        select meeting, code from (select distinct unnest(attendees) code) selected;
    update meetings set attendance_recorded_at = now() where id = meeting;
end;
$$;

-- Import all validated CSV rows in one transaction. Repeating an import preserves edits.
create function public.import_meeting_attendance(records jsonb)
returns integer language plpgsql set search_path = public as $$
declare r jsonb; meeting bigint; imported integer := 0;
begin
    for r in select * from jsonb_array_elements(records) loop
        insert into meetings(held_at, title, recording_id)
        values ((r->>'held_at')::timestamptz, r->>'title', r->>'recording_id')
        on conflict (recording_id) do nothing;
        select id into meeting from meetings where recording_id = r->>'recording_id' for update;
        if (select attendance_recorded_at is null from meetings where id = meeting) then
            perform save_meeting_attendance(meeting,
                array(select jsonb_array_elements_text(r->'attendees')));
            imported := imported + 1;
        end if;
    end loop;
    return imported;
end;
$$;
revoke all on function public.save_meeting_attendance(bigint, text[]) from public, anon, authenticated;
revoke all on function public.import_meeting_attendance(jsonb) from public, anon, authenticated;
grant execute on function public.save_meeting_attendance(bigint, text[]) to service_role;
grant execute on function public.import_meeting_attendance(jsonb) to service_role;
notify pgrst, 'reload schema';
commit;
