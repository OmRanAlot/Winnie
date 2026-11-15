-- Private, compact LangGraph checkpoints for verified Photon DM conversations.
begin;
create table public.photon_conversation_memory (
 member_code text not null references public.members(code) on delete cascade,
 thread_key text not null check(thread_key ~ '^[a-f0-9]{64}$'),
 version bigint not null default 1 check(version>0),
 state jsonb not null check(jsonb_typeof(state)='object' and octet_length(state::text)<=131072),
 updated_at timestamptz not null default now(),
 expires_at timestamptz not null,
 primary key(member_code,thread_key)
);
alter table public.photon_conversation_memory enable row level security;
revoke all on public.photon_conversation_memory from public,anon,authenticated;
grant all on public.photon_conversation_memory to service_role;
create index photon_conversation_memory_expiry on public.photon_conversation_memory(expires_at);

create function public.load_photon_memory(p_member text,p_thread text) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 if not exists(select 1 from public.members where code=p_member and active and contact_consent) then
  raise exception 'Active consenting membership is required'; end if;
 return (select to_jsonb(memory) from public.photon_conversation_memory memory
  where member_code=p_member and thread_key=p_thread);
end;
$$;
revoke all on function public.load_photon_memory(text,text) from public,anon,authenticated;
grant execute on function public.load_photon_memory(text,text) to service_role;

create function public.save_photon_memory(p_member text,p_thread text,p_expected bigint,p_state jsonb,p_ttl integer default 7200)
returns jsonb language plpgsql security definer set search_path='' as $$
declare saved public.photon_conversation_memory;
begin
 if not exists(select 1 from public.members where code=p_member and active and contact_consent) then
  raise exception 'Active consenting membership is required'; end if;
 if p_thread is null or p_thread !~ '^[a-f0-9]{64}$' or p_expected is null or p_expected<0 or p_ttl is null or p_ttl not between 60 and 86400
  or p_state is null or jsonb_typeof(p_state)<>'object' or octet_length(p_state::text)>131072 then
  raise exception 'Invalid memory checkpoint'; end if;
 -- Do not resurrect forgotten/changed context. A concurrent writer must reload.
 if p_expected=0 then
  insert into public.photon_conversation_memory(member_code,thread_key,state,expires_at)
   values(p_member,p_thread,p_state,now()+make_interval(secs=>p_ttl)) on conflict do nothing returning * into saved;
 else
  update public.photon_conversation_memory set state=p_state,version=version+1,updated_at=now(),expires_at=now()+make_interval(secs=>p_ttl)
   where member_code=p_member and thread_key=p_thread and version=p_expected returning * into saved;
 end if;
 if saved.member_code is null then raise exception 'Conversation changed; reload memory' using errcode='40001'; end if;
 -- Expired checkpoints are not used. Purge old rows with a safety window for in-flight requests.
 delete from public.photon_conversation_memory where expires_at<now()-interval '1 day';
 return to_jsonb(saved);
end;
$$;
revoke all on function public.save_photon_memory(text,text,bigint,jsonb,integer) from public,anon,authenticated;
grant execute on function public.save_photon_memory(text,text,bigint,jsonb,integer) to service_role;
comment on table public.photon_conversation_memory is
 'Server-only bounded conversational context. Identity is scoped by verified member plus hashed DM/semester. Not authority for task writes or approvals. Expired rows are ignored and purged on later saves.';
notify pgrst,'reload schema';
commit;
