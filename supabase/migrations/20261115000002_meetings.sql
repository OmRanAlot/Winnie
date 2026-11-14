-- Additive. Meetings, attendees, transcript segments, audio bucket. Safe to re-run.
do $$
begin
    -- A different, older `meetings` table (supabase/migrations/0001_init.sql) would make
    -- `create table if not exists` silently skip. Fail loudly instead.
    if to_regclass('public.meetings') is not null and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'meetings' and column_name = 'audio_sha256'
    ) then
        raise exception 'public.meetings already exists with a different shape; resolve manually';
    end if;
end $$;

create table if not exists public.meetings (
    id                  bigint generated always as identity primary key,
    title               text,
    held_at             timestamptz not null,
    duration_seconds    integer check (duration_seconds is null or duration_seconds >= 0),
    audio_bucket        text not null default 'meeting-audio',
    audio_path          text,
    audio_mime          text,
    audio_bytes         bigint check (audio_bytes is null or audio_bytes >= 0),
    audio_sha256        text unique,
    status              text not null default 'uploaded'
        check (status in ('uploaded', 'transcribing', 'summarizing',
                          'extracting_tasks', 'done', 'failed')),
    error               text,
    transcript_text     text,
    summary             text,
    transcription_model text,
    summary_model       text,
    transcript_tsv      tsvector generated always as
        (to_tsvector('english', coalesce(transcript_text, ''))) stored,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists meetings_held_at_idx on public.meetings (held_at desc);
create index if not exists meetings_transcript_tsv_idx
    on public.meetings using gin (transcript_tsv);

create or replace function public.meetings_set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
    new.updated_at := now();
    return new;
end;
$$;
drop trigger if exists meetings_updated_at on public.meetings;
create trigger meetings_updated_at before update on public.meetings
    for each row execute function public.meetings_set_updated_at();

create table if not exists public.meeting_attendees (
    meeting_id bigint not null references public.meetings (id) on delete cascade,
    member_id  bigint not null references public.members (id) on delete cascade,
    primary key (meeting_id, member_id)
);
create index if not exists meeting_attendees_member_id_idx
    on public.meeting_attendees (member_id);

create table if not exists public.transcript_segments (
    id            bigint generated always as identity primary key,
    meeting_id    bigint not null references public.meetings (id) on delete cascade,
    idx           integer not null,
    start_ms      integer,
    end_ms        integer,
    speaker_label text,
    member_id     bigint references public.members (id) on delete set null,
    text          text not null,
    unique (meeting_id, idx)
);
create index if not exists transcript_segments_member_id_idx
    on public.transcript_segments (member_id);

alter table public.meetings            enable row level security;
alter table public.meeting_attendees   enable row level security;
alter table public.transcript_segments enable row level security;

-- Private audio bucket. Guarded so the migration also runs on plain Postgres (no storage schema).
do $$
begin
    if to_regclass('storage.buckets') is not null then
        insert into storage.buckets (id, name, public)
        values ('meeting-audio', 'meeting-audio', false)
        on conflict (id) do nothing;
    end if;
end $$;
