-- Meeting ingest: keep the AI-written summary next to the transcript. Additive; tasks is untouched.
alter table public.meetings add column if not exists summary text;
