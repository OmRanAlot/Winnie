-- Private durable inbox for signed Photon webhooks. No roster data is altered.
begin;
create table public.photon_inbox (
 id uuid primary key default gen_random_uuid(),webhook_id uuid not null,message_id text not null,
 body_hash text not null,payload jsonb not null,
 state text not null default 'queued' check(state in ('queued','processing','ready','sending','sent','ignored','uncertain')),
 reply text,claim_token uuid,claimed_at timestamptz,provider_id text,created_at timestamptz not null default now(),
 unique(webhook_id,message_id)
);
alter table public.photon_inbox enable row level security;
revoke all on public.photon_inbox from public,anon,authenticated;
grant all on public.photon_inbox to service_role;
create function public.photon_inbox_put(p_webhook uuid,p_message text,p_hash text,p_payload jsonb)
returns uuid language plpgsql set search_path='' as $$
declare r public.photon_inbox;
begin
 insert into public.photon_inbox(webhook_id,message_id,body_hash,payload)
 values(p_webhook,p_message,p_hash,p_payload) on conflict do nothing;
 select * into strict r from public.photon_inbox where webhook_id=p_webhook and message_id=p_message;
 if r.body_hash<>p_hash then raise exception 'Webhook content changed'; end if;
 return r.id;
end;
$$;
create function public.photon_inbox_claim(p_id uuid,p_token uuid) returns jsonb language plpgsql set search_path='' as $$
declare r public.photon_inbox;
begin
 select * into strict r from public.photon_inbox where id=p_id for update;
 if r.state in ('sent','ignored','uncertain') then return jsonb_build_object('done',true); end if;
 if r.state='sending' then
  if r.claimed_at<now()-interval '2 minutes' then
   update public.photon_inbox set state='uncertain' where id=p_id;
   return jsonb_build_object('done',true);
  end if;
  return jsonb_build_object('busy',true);
 end if;
 if r.state in ('processing','ready') and r.claimed_at>now()-interval '2 minutes' then return jsonb_build_object('busy',true); end if;
 update public.photon_inbox set state=case when r.reply is null then 'processing' else 'ready' end,
  claim_token=p_token,claimed_at=now() where id=p_id;
 return jsonb_build_object('payload',r.payload,'reply',r.reply);
end;
$$;
create function public.photon_inbox_advance(p_id uuid,p_token uuid,p_state text,p_reply text default null,p_provider text default null)
returns boolean language plpgsql set search_path='' as $$
begin
 if p_state not in ('ready','sending','sent','ignored','uncertain') then raise exception 'Invalid inbox state'; end if;
 update public.photon_inbox set state=p_state,reply=coalesce(p_reply,reply),provider_id=coalesce(p_provider,provider_id),claimed_at=now()
 where id=p_id and claim_token=p_token and (
  (state='processing' and p_state in ('ready','ignored')) or (state='ready' and p_state='sending')
  or (state='sending' and p_state in ('sent','uncertain')));
 return found;
end;
$$;
revoke all on function public.photon_inbox_put(uuid,text,text,jsonb),public.photon_inbox_claim(uuid,uuid),public.photon_inbox_advance(uuid,uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.photon_inbox_put(uuid,text,text,jsonb),public.photon_inbox_claim(uuid,uuid),public.photon_inbox_advance(uuid,uuid,text,text,text) to service_role;
notify pgrst,'reload schema';
commit;
