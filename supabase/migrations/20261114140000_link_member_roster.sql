-- Extend the existing messaging roster; keep contact details server-only.
begin;

alter table public.members
    add column email text check (email = lower(trim(email)) and email like '%@%'),
    add column phone_number text check (length(phone_number) <= 50),
    add column contact_consent boolean not null default false,
    add column board_role text not null default 'member',
    add column girlhacks_title text,
    add column major text,
    add column graduation_date text,
    add column graduation_year integer check (graduation_year between 2000 and 2200),
    add column skills text[] not null default '{}',
    add column role_description text not null default '',
    add column role_responsibilities text[] not null default '{}',
    add column delegation_context_verified boolean not null default false,
    add constraint members_contact_consent check (
        contact_consent or (email is null and phone_number is null)
    );

create unique index members_email_unique on public.members (email) where email is not null;

alter table public.profiles
    add column member_code text unique references public.members(code) on delete set null,
    add column girlhacks_title text,
    add column major text,
    add column graduation_date text,
    add column graduation_year integer check (graduation_year between 2000 and 2200);

-- Only verified Auth email addresses can claim the roster's predetermined profile.
-- Self-editable user_metadata never supplies board roles, membership, or admin status.
create or replace function public.sync_auth_profile() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
    member public.members%rowtype;
    linked_code text;
begin
    select member_code into linked_code from public.profiles where id = new.id;
    if tg_op = 'UPDATE' and linked_code is not null
        and new.email is distinct from old.email then
        raise exception 'Contact an administrator to change your registered email';
    end if;

    insert into public.profiles (id, name, email)
    values (new.id, left(coalesce(new.raw_user_meta_data ->> 'name', ''), 200), new.email)
    on conflict (id) do update set email = excluded.email;

    if new.email_confirmed_at is not null then
        select * into member from public.members
        where email = lower(trim(new.email)) and contact_consent and active;
        if found then
            update public.profiles set
                member_code = member.code,
                name = member.display_name,
                role = member.board_role,
                phone_number = member.phone_number,
                skills = case when profiles.member_code is null
                    then member.skills else profiles.skills end,
                girlhacks_title = member.girlhacks_title,
                major = member.major,
                graduation_date = member.graduation_date,
                graduation_year = member.graduation_year
            where id = new.id;
        end if;
    end if;
    return new;
end;
$$;

drop trigger sync_auth_profile on auth.users;
create trigger sync_auth_profile
after insert or update of email, email_confirmed_at on auth.users
for each row execute function public.sync_auth_profile();

-- Importing a roster after inviting someone also fills their existing profile.
create function public.sync_roster_profile() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    if new.email is not null and new.contact_consent and new.active then
        update public.profiles p set
            member_code = new.code, name = new.display_name, role = new.board_role,
            phone_number = new.phone_number,
            skills = case when p.member_code is null then new.skills else p.skills end,
            girlhacks_title = new.girlhacks_title, major = new.major,
            graduation_date = new.graduation_date, graduation_year = new.graduation_year
        from auth.users u where p.id = u.id
            and lower(trim(u.email)) = new.email and u.email_confirmed_at is not null;
    end if;
    return new;
end;
$$;

create trigger sync_roster_profile after insert or update on public.members
for each row execute function public.sync_roster_profile();

revoke all on function public.sync_roster_profile() from public, anon, authenticated;

-- Transactional, server-only importer. No invitations or messaging identities are created.
create function public.import_member_roster(records jsonb) returns integer
language plpgsql set search_path = '' as $$
declare
    item jsonb;
    matched_code text;
    matching_count integer;
    imported integer := 0;
begin
    if jsonb_typeof(records) is distinct from 'array' or jsonb_array_length(records) > 100 then
        raise exception 'Expected at most 100 roster records';
    end if;
    for item in select value from jsonb_array_elements(records) loop
        select count(*), min(code) into matching_count, matched_code from public.members
        where lower(trim(display_name)) = lower(trim(item ->> 'display_name'));
        if matching_count > 1 then
            raise exception 'Ambiguous existing roster name; resolve member codes manually';
        end if;
        matched_code := coalesce(matched_code, item ->> 'code');
        if exists (select 1 from public.members where code = matched_code
            and lower(trim(display_name)) <> lower(trim(item ->> 'display_name'))) then
            raise exception 'Member code belongs to another person';
        end if;
        insert into public.members (
            code, display_name, email, phone_number, contact_consent, board_role,
            girlhacks_title, major, graduation_date, graduation_year,
            role_description, role_responsibilities, delegation_context_verified
        ) values (
            matched_code, item ->> 'display_name', item ->> 'email', item ->> 'phone_number',
            coalesce((item ->> 'contact_consent')::boolean, false), item ->> 'board_role',
            item ->> 'girlhacks_title', item ->> 'major', item ->> 'graduation_date',
            (item ->> 'graduation_year')::integer, coalesce(item ->> 'role_description', ''),
            array(select jsonb_array_elements_text(item -> 'role_responsibilities')),
            coalesce((item ->> 'delegation_context_verified')::boolean, false)
        ) on conflict (code) do update set
            display_name = excluded.display_name, email = excluded.email,
            phone_number = excluded.phone_number, contact_consent = excluded.contact_consent,
            board_role = excluded.board_role, girlhacks_title = excluded.girlhacks_title,
            major = excluded.major, graduation_date = excluded.graduation_date,
            graduation_year = excluded.graduation_year,
            role_description = excluded.role_description,
            role_responsibilities = excluded.role_responsibilities,
            delegation_context_verified = excluded.delegation_context_verified;
        imported := imported + 1;
    end loop;
    return imported;
end;
$$;

revoke all on function public.import_member_roster(jsonb) from public, anon, authenticated;
grant execute on function public.import_member_roster(jsonb) to service_role;

notify pgrst, 'reload schema';
commit;
