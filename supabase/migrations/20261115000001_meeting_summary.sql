-- Also supports databases that started directly with the UUID task migration.
create table if not exists public.meetings (
    id bigint generated always as identity primary key,
    held_at timestamptz not null,
    title text,
    transcript text,
    recording_id text unique
);
alter table public.meetings enable row level security;
revoke all on public.meetings from anon, authenticated;
grant all on public.meetings to service_role;
grant usage, select on sequence public.meetings_id_seq to service_role;
-- Meeting ingest: keep the AI-written summary next to the transcript. Additive; tasks is untouched.
alter table public.meetings add column if not exists summary text;
