-- Keep daily send deduplication while allowing an obsolete, never-sent nudge to refresh.
begin;
create or replace function public.enqueue_task_notification(p_task uuid,p_kind text,p_key text,p_expires timestamptz default null)
returns integer language plpgsql security definer set search_path='' as $$
declare t public.tasks; codes text[]; inserted integer;
begin
 select * into t from public.tasks where id=p_task;
 if not found or t.status='done' then return 0; end if;
 codes:=public.task_notification_recipients(t);
 insert into public.task_notifications(task_id,kind,event_key,recipient_code,owner_snapshot,assignee_snapshot,due_snapshot,due_time_snapshot,expires_at)
  select t.id,p_kind,p_key,m.code,t.owner_code,t.assignee_text,t.due_date,t.due_time,p_expires
   from public.members m where m.active and m.code=any(codes)
    and (p_kind<>'nudge' or (m.contact_consent and exists(
     select 1 from public.member_identities i where i.member_code=m.code
      and i.platform='imessage' and i.reminders_enabled)))
  on conflict(task_id,kind,event_key,recipient_code) do update set
   owner_snapshot=excluded.owner_snapshot,assignee_snapshot=excluded.assignee_snapshot,
   due_snapshot=excluded.due_snapshot,due_time_snapshot=excluded.due_time_snapshot,
   status='pending',expires_at=excluded.expires_at
  -- Never reset an attempted send, even when its provider outcome is uncertain.
  where task_notifications.started_at is null
   and task_notifications.status in ('pending','cancelled') and
    (task_notifications.status='cancelled' or row(task_notifications.owner_snapshot,task_notifications.assignee_snapshot,task_notifications.due_snapshot,task_notifications.due_time_snapshot)
     is distinct from row(excluded.owner_snapshot,excluded.assignee_snapshot,excluded.due_snapshot,excluded.due_time_snapshot));
 get diagnostics inserted=row_count; return inserted;
end;
$$;
revoke all on function public.enqueue_task_notification(uuid,text,text,timestamptz) from public,anon,authenticated;
grant execute on function public.enqueue_task_notification(uuid,text,text,timestamptz) to service_role;
notify pgrst,'reload schema';
commit;
