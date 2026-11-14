-- Password completion is derived from Auth's managed hash, never from client metadata.
begin;
alter table public.profiles add column if not exists password_setup_complete boolean not null default false;

update public.profiles p set password_setup_complete =
    coalesce(length(u.encrypted_password) > 0, false)
from auth.users u where u.id = p.id;

create or replace function public.sync_password_setup() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    update public.profiles set password_setup_complete =
        coalesce(length(new.encrypted_password) > 0, false)
    where id = new.id;
    return new;
end;
$$;
revoke all on function public.sync_password_setup() from public, anon, authenticated;

-- Trigger order ensures sync_auth_profile creates the row before this trigger runs.
drop trigger if exists sync_password_setup on auth.users;
create trigger sync_password_setup after insert or update of encrypted_password on auth.users
for each row execute function public.sync_password_setup();

-- Direct browser RPCs must enforce the same membership gate as FastAPI.
create or replace function public.current_board_member_code() returns text
language sql stable security definer set search_path = '' as $$
    select m.code from public.profiles p
    join public.members m on m.code = p.member_code
    join auth.users u on u.id = p.id
    where p.id = auth.uid() and p.password_setup_complete
        and u.email_confirmed_at is not null and m.active and m.contact_consent
        and m.email = lower(trim(u.email)) and lower(trim(p.email)) = m.email;
$$;
revoke all on function public.current_board_member_code() from public, anon;
grant execute on function public.current_board_member_code() to authenticated, service_role;

-- Some installations have not deployed the reassignment feature yet.
do $$
begin
    if to_regclass('public.task_reassignment_requests') is not null then
        execute $fn$
            create or replace function public.can_review_task_requests() returns boolean
            language sql stable security definer set search_path = '' as $body$
                select exists (
                    select 1 from public.profiles p join public.members m on m.code = p.member_code
                    where p.id = auth.uid() and m.code = public.current_board_member_code()
                        and (p.is_admin or lower(trim(m.board_role)) in ('president', 'vice president'))
                );
            $body$;
        $fn$;
        execute $fn$
            create or replace function public.submit_task_reassignment(
                p_task_id uuid, p_proposed_assignee_code text, p_reason text default ''
            ) returns public.task_reassignment_requests
            language plpgsql security definer set search_path = '' as $body$
            declare
                requester text := public.current_board_member_code();
                result public.task_reassignment_requests;
            begin
                if requester is null then
                    raise exception 'A verified active member with completed password setup is required';
                end if;
                insert into public.task_reassignment_requests (
                    task_id, requester_code, proposed_assignee_code, reason
                ) values (p_task_id, requester, p_proposed_assignee_code, p_reason)
                returning * into result;
                return result;
            end;
            $body$;
        $fn$;
        execute 'drop policy if exists task_reassignment_read on public.task_reassignment_requests';
        execute $policy$
            create policy task_reassignment_read on public.task_reassignment_requests
            for select to authenticated using (
                public.can_review_task_requests() or requester_code = public.current_board_member_code()
            );
        $policy$;
    end if;
end;
$$;

notify pgrst, 'reload schema';
commit;
