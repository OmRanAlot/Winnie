-- Read-only, sender-scoped request facts for natural-language decisions.
begin;
create function public.messaging_request_context(p_platform text,p_sender_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare actor text; reviewer boolean; result jsonb;
begin
 if p_platform<>'imessage' then raise exception 'Use a linked direct-message identity'; end if;
 select m.code into actor from public.member_identities i join public.members m on m.code=i.member_code
  where i.platform=p_platform and i.sender_id=p_sender_id and m.active and m.contact_consent;
 if actor is null then raise exception 'Your messaging identity is not linked to an active consenting member'; end if;
 select p.is_admin or lower(trim(m.board_role)) in ('president','vice president') into strict reviewer
  from public.profiles p join public.members m on m.code=p.member_code join auth.users u on u.id=p.id
  where m.code=actor and p.password_setup_complete and u.email_confirmed_at is not null
   and m.email=lower(trim(u.email)) and lower(trim(p.email))=m.email;
 select coalesce(jsonb_agg(jsonb_build_object('request_no',r.request_no,'title',t.title,'task_code',t.task_code,
  'requester_name',a.display_name,'recipient_name',b.display_name,'admin_decision',r.admin_decision,
  'recipient_decision',r.recipient_decision,'incoming',r.proposed_assignee_code=actor,
  'can_review',reviewer and r.admin_decision='pending',
  'can_respond',r.proposed_assignee_code=actor and r.admin_decision='approved' and r.recipient_decision='pending')
  order by r.created_at,r.id),'[]') into result
  from public.task_reassignment_requests r join public.tasks t on t.id=r.task_id
   join public.members a on a.code=r.requester_code join public.members b on b.code=r.proposed_assignee_code
  where r.status='pending' and (reviewer or r.requester_code=actor or r.proposed_assignee_code=actor);
 return jsonb_build_object('can_review',reviewer,'requests',result);
exception when no_data_found or too_many_rows then
 raise exception 'A unique verified roster-linked account with completed password setup is required';
end;
$$;
revoke all on function public.messaging_request_context(text,text) from public,anon,authenticated;
grant execute on function public.messaging_request_context(text,text) to service_role;
notify pgrst,'reload schema';
commit;
