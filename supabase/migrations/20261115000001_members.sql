-- Additive. Members: people and/or seats, depending on what tasks.owner_code refers to.
-- `code` follows the same convention as tasks.owner_code (^[A-Z][A-Z0-9_-]{0,49}$).
-- Safe to re-run. Never touches public.tasks / public.tasks_placeholder.

create table if not exists public.members (
    id      bigint generated always as identity primary key,
    code    text not null unique check (code ~ '^[A-Z][A-Z0-9_-]{0,49}$'),
    kind    text not null default 'person' check (kind in ('person', 'seat')),
    name    text not null check (length(trim(name)) > 0),
    seat    text,
    aliases text[] not null default '{}',
    active  boolean not null default true
);

alter table public.members enable row level security;
