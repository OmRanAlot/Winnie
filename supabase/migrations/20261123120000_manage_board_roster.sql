-- Manage people and contacts without deleting historical member references.
begin;

create function public.save_board_member(
    actor uuid, member text, semester text, changes jsonb, create_member boolean
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
    actor_code text;
    previous public.members;
    saved public.members;
    next_name text;
    next_role text;
    next_email text;
    next_phone text;
    next_consent boolean;
    next_active boolean;
    old_phone_digits text;
    next_phone_digits text;
begin
    -- Hold the acting membership until commit so it cannot be revoked mid-write.
    select m.code into actor_code from public.members m
    join public.profiles p on p.member_code = m.code
    join auth.users u on u.id = p.id
    where p.id = actor and p.is_admin and p.password_setup_complete
        and m.active and m.contact_consent and u.email_confirmed_at is not null
        and m.email = lower(trim(u.email)) and m.email = lower(trim(p.email))
    for update of m, p;
    if not found then
        raise exception 'Administrator access is required' using errcode = '42501';
    end if;

    if jsonb_typeof(changes) is distinct from 'object' or exists (
        select 1 from jsonb_object_keys(changes) k
        where k not in ('display_name', 'board_role', 'email', 'phone_number', 'contact_consent', 'active')
    ) then
        raise exception 'Unsupported roster field' using errcode = '22023';
    end if;

    if not create_member then
        select * into previous from public.members where code = member for update;
        if not found then
            raise exception 'Member not found' using errcode = 'P0002';
        end if;
    end if;

    next_name := case when changes ? 'display_name' then trim(changes->>'display_name')
        else previous.display_name end;
    next_role := case when changes ? 'board_role' then coalesce(nullif(trim(changes->>'board_role'), ''), 'member')
        else coalesce(previous.board_role, 'member') end;
    next_email := case when changes ? 'email' then nullif(lower(trim(changes->>'email')), '')
        else previous.email end;
    next_phone := case when changes ? 'phone_number' then nullif(trim(changes->>'phone_number'), '')
        else previous.phone_number end;
    next_consent := coalesce((changes->>'contact_consent')::boolean, previous.contact_consent, false);
    next_active := coalesce((changes->>'active')::boolean, previous.active, true);

    if not next_consent and (next_email is not null or next_phone is not null) then
        raise exception 'Confirm the member gave permission to store their contact details'
            using errcode = '22023';
    end if;
    if member = actor_code and (not next_active or next_email is distinct from previous.email) then
        raise exception 'Ask another administrator to change your sign-in email or remove your roster access'
            using errcode = '22023';
    end if;
    if next_email is not null and next_email is distinct from previous.email and exists (
        select 1 from public.profiles p
        where lower(trim(p.email)) = next_email and p.member_code is not null and p.member_code <> member
    ) then
        raise exception 'That email is already linked to another member' using errcode = '23505';
    end if;
    if (create_member or next_name is distinct from previous.display_name) and exists (
        select 1 from public.members m where m.code <> member and lower(trim(m.display_name)) = lower(next_name)
    ) then
        raise exception 'That name is already on the board roster' using errcode = '23505';
    end if;

    if create_member then
        insert into public.members (code, display_name, board_role, email, phone_number, contact_consent)
        values (member, next_name, next_role, next_email, next_phone, next_consent) returning * into saved;
    else
        if next_email is distinct from previous.email then
            -- Keep the old profile for history, and let the established verified-email trigger
            -- link the replacement account. The old account's privileges cannot follow it.
            update public.profiles set member_code = null, is_admin = false, phone_number = null
            where member_code = member;
        end if;

        update public.members set
            display_name = next_name, board_role = next_role, email = next_email, phone_number = next_phone,
            contact_consent = next_consent, active = next_active,
            role_description = case when next_role = previous.board_role then previous.role_description else '' end,
            role_responsibilities = case when next_role = previous.board_role then previous.role_responsibilities
                else '{}'::text[] end,
            delegation_context_verified = next_role = previous.board_role and previous.delegation_context_verified
        where code = member returning * into saved;

        -- An edited contact must not leave a superseded sender authorized. New contacts
        -- have no messaging permissions until registered through the verified sender flow.
        old_phone_digits := regexp_replace(previous.phone_number, '[^0-9]', '', 'g');
        next_phone_digits := regexp_replace(next_phone, '[^0-9]', '', 'g');
        if length(old_phone_digits) = 10 and previous.phone_number not like '+%' then
            old_phone_digits := '1' || old_phone_digits;
        end if;
        if length(next_phone_digits) = 10 and next_phone not like '+%' then
            next_phone_digits := '1' || next_phone_digits;
        end if;
        delete from public.member_identities i where i.member_code = member and (
            (previous.contact_consent and not next_consent)
            or (next_email is distinct from previous.email and lower(i.sender_id) = previous.email)
            or (next_phone_digits is distinct from old_phone_digits and length(old_phone_digits) >= 7
                and (i.sender_id ~ '^[+0-9(). -]+$') and (
                    regexp_replace(i.sender_id, '[^0-9]', '', 'g') = old_phone_digits
                    or (length(old_phone_digits) = 11 and old_phone_digits like '1%'
                        and regexp_replace(i.sender_id, '[^0-9]', '', 'g') = substr(old_phone_digits, 2))
                ))
        );
    end if;

    if create_member or next_name is distinct from previous.display_name then
        -- Keep previous aliases for tasks that were assigned before a rename.
        insert into public.member_aliases as a (semester_code, alias, member_code)
        values (semester, next_name, member)
        on conflict (semester_code, lower(trim(alias))) do update set alias = excluded.alias
        where a.member_code = excluded.member_code;
        if not found then
            raise exception 'That name is already used in the current task tracker. Enter a distinct name.'
                using errcode = '23505', constraint = 'member_aliases_semester_alias_idx';
        end if;
    end if;

    return jsonb_build_object(
        'code', saved.code, 'display_name', saved.display_name, 'board_role', saved.board_role,
        'email', saved.email, 'phone_number', saved.phone_number, 'contact_consent', saved.contact_consent,
        'active', saved.active
    );
end;
$$;
-- Read auth.users for the verified administrator check via a narrowly scoped server-only RPC.
revoke all on function public.save_board_member(uuid,text,text,jsonb,boolean) from public, anon, authenticated;
grant execute on function public.save_board_member(uuid,text,text,jsonb,boolean) to service_role;
notify pgrst, 'reload schema';
commit;
