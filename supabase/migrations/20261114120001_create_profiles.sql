-- App profiles are linked to Supabase Auth; passwords are never stored here.
begin;

create table public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    name text not null default '' check (length(name) <= 200),
    email text,
    phone_number text check (length(phone_number) <= 50),
    role text not null default 'member'
        check (length(trim(role)) between 1 and 100),
    is_admin boolean not null default false,
    skills text[] not null default '{}'
        check (cardinality(skills) <= 50 and array_position(skills, null) is null),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on column public.profiles.email is
    'Read-only mirror of auth.users.email; change email through Supabase Auth.';
comment on column public.profiles.phone_number is
    'Contact number only, not a verified Supabase Auth login phone number.';
comment on column public.profiles.role is
    'Board position, managed by trusted backend code; distinct from Auth JWT role.';
comment on column public.profiles.is_admin is
    'App administrator flag; writable only by trusted server/database access.';

-- This function is only invoked by the Auth trigger, not exposed as a callable RPC.
-- User-editable metadata may supply a display name, never role or admin privileges.
create function public.sync_auth_profile() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    insert into public.profiles (id, name, email)
    values (
        new.id,
        left(coalesce(new.raw_user_meta_data ->> 'name', ''), 200),
        new.email
    )
    on conflict (id) do update set email = excluded.email;
    return new;
end;
$$;

revoke all on function public.sync_auth_profile() from public, anon, authenticated;

create trigger sync_auth_profile
after insert or update of email on auth.users
for each row execute function public.sync_auth_profile();

-- Create profiles for any Auth accounts that existed before this migration.
insert into public.profiles (id, name, email)
select id, left(coalesce(raw_user_meta_data ->> 'name', ''), 200), email
from auth.users
on conflict (id) do nothing;

create function public.touch_profile() returns trigger
language plpgsql set search_path = '' as $$
begin
    if tg_op = 'UPDATE' then
        new.created_at := old.created_at;
    end if;
    new.updated_at := now();
    if exists (
        select 1 from unnest(new.skills) as skill
        where length(trim(skill)) not between 1 and 100
    ) then
        raise exception 'Each skill must contain between 1 and 100 characters';
    end if;
    return new;
end;
$$;

revoke all on function public.touch_profile() from public, anon, authenticated;

create trigger touch_profile before insert or update on public.profiles
for each row execute function public.touch_profile();

alter table public.profiles enable row level security;

-- Explicitly revoke table-wide privileges before allowing only safe column edits.
revoke all on public.profiles from public, anon, authenticated;
grant select on public.profiles to authenticated;
grant update (name, phone_number, skills) on public.profiles to authenticated;
grant all on public.profiles to service_role;

create policy profiles_read_own on public.profiles
for select to authenticated using ((select auth.uid()) = id);

create policy profiles_update_own on public.profiles
for update to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

commit;
