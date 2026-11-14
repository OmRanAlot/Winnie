-- Admin-managed messaging identities. Independent of frontend Supabase Auth sessions.
begin;

create table public.members (
    code text primary key check (code ~ '^[A-Z][A-Z0-9_-]{0,49}$'),
    display_name text not null check (length(trim(display_name)) between 1 and 200),
    active boolean not null default true
);

create table public.member_identities (
    platform text not null check (platform = 'imessage'),
    sender_id text not null check (length(trim(sender_id)) between 1 and 500),
    member_code text not null references public.members(code),
    primary key (platform, sender_id),
    check (sender_id = trim(sender_id)),
    check (position('@' in sender_id) = 0 or sender_id = lower(sender_id))
);

create table public.member_aliases (
    semester_code text not null
        check (semester_code ~ '^(spring|summer|fall|winter)-[0-9]{4}$'),
    alias text not null check (length(trim(alias)) between 1 and 200),
    member_code text not null references public.members(code)
);

-- One name/email cannot identify two people within the same semester.
create unique index member_aliases_semester_alias_idx
    on public.member_aliases (semester_code, lower(trim(alias)));
create index member_aliases_member_idx on public.member_aliases (member_code);

alter table public.members enable row level security;
alter table public.member_identities enable row level security;
alter table public.member_aliases enable row level security;
revoke all on public.members, public.member_identities, public.member_aliases
    from anon, authenticated;
grant all on public.members, public.member_identities, public.member_aliases to service_role;

notify pgrst, 'reload schema';
commit;
