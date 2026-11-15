import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';
const folder = new URL('../migrations/', import.meta.url);
const migrations = await Promise.all((await readdir(folder)).filter(n => n.endsWith('.sql')).sort().map(n => readFile(new URL(n,folder),'utf8')));
const ids = {OWNER:'11111111-1111-4111-8111-111111111111',TARGET:'22222222-2222-4222-8222-222222222222',ADMIN:'33333333-3333-4333-8333-333333333333',OTHER:'44444444-4444-4444-8444-444444444444'};
async function as(db, code) {
  await db.exec('reset role');
  await db.query("select set_config('request.jwt.claim.sub',$1,false)",[ids[code] || '']);
  await db.exec(code ? 'set role authenticated' : 'set role anon');
}
async function setup(beforeUpgrade=false) {
  const db = new PGlite();
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; grant usage on schema public,auth to anon,authenticated,service_role;
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,encrypted_password text,raw_user_meta_data jsonb default '{}');`);
  for (const sql of migrations) {
    if(beforeUpgrade && sql.includes('-- Admin authorizes the proposal first')) break;
    await db.exec(sql);
  }
  for (const [code,id] of Object.entries(ids)) {
    const email = code.toLowerCase()+'@example.com';
    await db.query('insert into members(code,display_name,board_role,email,contact_consent) values($1,$1,$2,$3,true)',[code,code==='ADMIN'?'President':'Member',email]);
    await db.query('insert into auth.users(id,email,email_confirmed_at) values($1,$2,now())',[id,email]);
    await db.query("update auth.users set encrypted_password='synthetic-hash' where id=$1",[id]);
    await db.query('update profiles set is_admin=$2 where id=$1',[id,code==='ADMIN']);
  }
  const task = (await db.query("insert into tasks(title,month_code,owner_code,assignee_text) values('Synthetic task','2026-11','OWNER','OWNER') returning *")).rows[0];
  await as(db,'OWNER');
  const request = (await db.query('select * from submit_task_reassignment($1,$2,$3)',[task.id,'TARGET','Schedule conflict'])).rows[0];
  return {db,task,request};
}
async function owner(db,id) {
  await db.exec('reset role');
  return (await db.query('select owner_code,original_assignee_code from tasks where id=$1',[id])).rows[0];
}


async function photon(db,code,event,action,payload={}) {
 await db.exec('reset role; set role service_role');
 return (await db.query('select messaging_reassignment($1,$2,$3,$4,$5::jsonb) result',
  ['imessage',code.toLowerCase()+'@example.com',event,action,JSON.stringify(payload)])).rows[0].result;
}
async function identities(db) {
 await db.exec('reset role');
 for(const code of Object.keys(ids)) await db.query("insert into member_identities(platform,sender_id,member_code,reminders_enabled) values('imessage',$1,$2,true)",[code.toLowerCase()+'@example.com',code]);
}
test('admin approval first queues consent; only recipient acceptance transfers and records outgoing owner',async()=>{
 const {db,task,request}=await setup();
 try {
  await identities(db); await as(db,'TARGET');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/Administrator approval is required/);
  await as(db,'OTHER');
  assert.equal((await db.query('select id from task_reassignment_requests')).rows.length,0);
  await assert.rejects(db.query('select review_task_reassignment($1,$2)',[request.id,'approved']),/Only the president/);
  await db.exec('reset role; set role service_role');
  const adminNotice=(await db.query('select claim_reassignment_notification() n')).rows[0].n;
  assert.equal(adminNotice.recipient,'admin@example.com'); assert.match(adminNotice.text,/approve REQ-/);
  await as(db,'ADMIN');
  const authorized=(await db.query('select * from review_task_reassignment($1,$2)',[request.id,'approved'])).rows[0];
  assert.equal(authorized.status,'pending'); assert.equal(authorized.admin_decision,'approved');
  assert.equal((await owner(db,task.id)).owner_code,'OWNER');
  await db.exec('set role service_role');
  const recipientNotice=(await db.query('select claim_reassignment_notification() n')).rows[0].n;
  assert.equal(recipientNotice.recipient,'target@example.com'); assert.match(recipientNotice.text,/administrator approved/);
  await as(db,'OWNER');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/Incoming request not found/);
  await as(db,'TARGET');
  await assert.rejects(db.query("update task_reassignment_requests set recipient_decision='accepted' where id=$1",[request.id]),/permission denied/);
  const completed=(await db.query('select * from respond_task_reassignment($1,$2)',[request.id,'accepted'])).rows[0];
  assert.equal(completed.status,'approved'); assert.ok(completed.handoff_completed_at);
  assert.equal(completed.requester_code,'OWNER'); assert.equal(completed.previous_owner_code,'OWNER');
  assert.equal(completed.reviewed_by_profile_id,ids.ADMIN); assert.equal(completed.responded_by_profile_id,ids.TARGET);
  assert.equal(new Date(completed.reviewed_at).getTime(),new Date(authorized.reviewed_at).getTime());
  assert.deepEqual(await owner(db,task.id),{owner_code:'TARGET',original_assignee_code:'OWNER'});
  await as(db,'TARGET');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'denied']),/already been answered/);
 } finally {await db.close();}
});
test('admin rejection and post-approval recipient denial preserve ownership',async()=>{
 const {db,task,request}=await setup();
 try {
  await as(db,'ADMIN'); await db.query('select review_task_reassignment($1,$2)',[request.id,'rejected']);
  await as(db,'TARGET');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/already been answered/);
  assert.equal((await owner(db,task.id)).owner_code,'OWNER');
  await as(db,'OWNER');
  const next=(await db.query('select * from submit_task_reassignment($1,$2)',[task.id,'TARGET'])).rows[0];
  await as(db,'ADMIN'); await db.query('select review_task_reassignment($1,$2)',[next.id,'approved']);
  await as(db,'TARGET');
  const denied=(await db.query('select * from respond_task_reassignment($1,$2)',[next.id,'denied'])).rows[0];
  assert.equal(denied.status,'declined'); assert.equal(denied.admin_decision,'approved');
  assert.equal(denied.handoff_completed_at,null);
  assert.equal((await owner(db,task.id)).owner_code,'OWNER');
 } finally {await db.close();}
});
test('stale ownership, completed tasks and revoked consent cannot complete an authorized transfer',async()=>{
 const {db,task,request}=await setup();
 try {
  await as(db,'ADMIN'); await db.query('select review_task_reassignment($1,$2)',[request.id,'approved']);
  await db.exec('reset role'); await db.query("update tasks set owner_code='OTHER' where id=$1",[task.id]);
  await as(db,'TARGET');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/assignment changed/);
  await db.exec('reset role'); await db.query("update tasks set owner_code='OWNER',status='done' where id=$1",[task.id]);
  await as(db,'TARGET');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/Completed tasks/);
  await db.exec('reset role'); await db.query("update tasks set status='todo' where id=$1",[task.id]);
  await db.exec("update members set active=false where code='TARGET'");
  await as(db,'TARGET');
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/verified active/);
  await as(db,null);
  await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/permission denied/);
 } finally {await db.close();}
});
test('Photon admin review and browser consent share the queue and replay-safe receipts',async()=>{
 const {db,task,request}=await setup();
 try {
  await identities(db);
  const approved=await photon(db,'ADMIN','authorize','approved',{request_no:request.request_no});
  assert.equal(approved.admin_decision,'approved'); assert.equal(approved.status,'pending');
  assert.deepEqual(await photon(db,'ADMIN','authorize','approved',{request_no:request.request_no}),approved);
  await assert.rejects(photon(db,'ADMIN','authorize','rejected',{request_no:request.request_no}),/content changed/);
  const listed=await photon(db,'TARGET','list','list'); assert.equal(listed.requests[0].admin_decision,'approved');
  const completed=await photon(db,'TARGET','accept','accepted',{request_no:request.request_no});
  assert.equal(completed.status,'approved');
  assert.deepEqual(await photon(db,'TARGET','accept','accepted',{request_no:request.request_no}),completed);
  assert.deepEqual(await owner(db,task.id),{owner_code:'TARGET',original_assignee_code:'OWNER'});
  await db.exec('set role service_role');
  assert.equal((await db.query("select count(*)::int n from reassignment_notifications where event='decision_v2'")).rows[0].n,2);
 } finally {await db.close();}
});
test('HELP selection delegates to the admin-first queue without legacy ownership writes',async()=>{
 const {db,task,request}=await setup();
 try {
  await identities(db); await db.exec('reset role');
  const h=(await db.query(`insert into task_help_requests(task_id,requester_code,task_version,status,candidates)
   select id,'OWNER',updated_at,'suggestions_ready','[{"code":"TARGET","name":"Target"}]'::jsonb from tasks where id=$1 returning *`,[task.id])).rows[0];
  await db.exec('set role service_role');
  const reply=(await db.query("select help_transition($1,$2,'select','OWNER','[]','TARGET',null) result",[h.request_no,h.revision])).rows[0].result.reply;
  assert.match(reply,/admin reviews first/i);
  assert.equal((await db.query('select count(*)::int n from task_reassignment_requests')).rows[0].n,1);
  assert.equal((await db.query('select reassignment_id from task_help_requests where request_no=$1',[h.request_no])).rows[0].reassignment_id,request.id);
  await assert.rejects(db.query("select help_transition($1,$2,'approve',null,'[]',null,'TARGET')",[h.request_no,h.revision+1]),/Legacy approval is disabled/);
  await assert.rejects(db.query("select help_transition_legacy($1,$2,'approve',null,'[]',null,'TARGET')",[h.request_no,h.revision+1]),/permission denied/);
 } finally {await db.close();}
});

test('upgrade preserves historical transfers and archives early consent before re-requesting it after admin review',async()=>{
 const {db,task,request}=await setup(true);
 try {
  await as(db,'TARGET'); await db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']);
  await db.exec('reset role');
  const historic=(await db.query("insert into tasks(title,month_code,owner_code,assignee_text) values('Historic task','2026-11','OWNER','OWNER') returning *")).rows[0];
  await as(db,'OWNER');
  const old=(await db.query('select * from submit_task_reassignment($1,$2)',[historic.id,'TARGET'])).rows[0];
  await as(db,'TARGET'); await db.query('select respond_task_reassignment($1,$2)',[old.id,'accepted']);
  await as(db,'ADMIN'); await db.query('select review_task_reassignment($1,$2)',[old.id,'approved']);
  await db.exec('reset role');
  const first=migrations.findIndex(sql=>sql.includes('-- Admin authorizes the proposal first'));
  for(const sql of migrations.slice(first)) await db.exec(sql);
  const open=(await db.query('select * from task_reassignment_requests where id=$1',[request.id])).rows[0];
  assert.equal(open.recipient_decision,'pending'); assert.equal(open.admin_decision,'pending');
  assert.equal(open.legacy_recipient_response.decision,'accepted');
  assert.equal(open.legacy_recipient_response.profile_id,ids.TARGET);
  assert.equal((await owner(db,task.id)).owner_code,'OWNER');
  const history=(await db.query('select * from task_reassignment_requests where id=$1',[old.id])).rows[0];
  assert.equal(history.status,'approved'); assert.ok(history.handoff_completed_at);
  assert.deepEqual(await owner(db,historic.id),{owner_code:'TARGET',original_assignee_code:'OWNER'});
  assert.equal((await db.query("select count(*)::int n from reassignment_notifications where request_id=$1 and event='admin_review' and status='pending'",[request.id])).rows[0].n,1);
  assert.equal((await db.query("select count(*)::int n from reassignment_notifications where request_id=$1 and event='incoming' and status='pending'",[request.id])).rows[0].n,0);
 } finally {await db.close();}
});

test('conversational context derives current role/stage from phone identity and does not consume action receipts',async()=>{
 const {db,request}=await setup();
 try {
  await identities(db); await db.exec('set role service_role');
  async function context(code) {
   return (await db.query("select messaging_request_context('imessage',$1) result",[code.toLowerCase()+'@example.com'])).rows[0].result;
  }
  assert.equal((await context('ADMIN')).requests[0].can_review,true);
  assert.equal((await context('TARGET')).requests[0].can_respond,false);
  assert.equal((await context('OWNER')).requests[0].can_review,false);
  assert.equal((await context('OTHER')).requests.length,0);
  assert.equal((await db.query('select count(*)::int n from reassignment_message_receipts')).rows[0].n,0);
  await photon(db,'ADMIN','natural-approve','approved',{request_no:request.request_no});
  assert.equal((await context('ADMIN')).requests[0].can_review,false);
  assert.equal((await context('TARGET')).requests[0].can_respond,true);
  await photon(db,'TARGET','natural-deny','denied',{request_no:request.request_no});
  assert.equal((await context('ADMIN')).requests.length,0);
  await db.exec('reset role; set role authenticated');
  await assert.rejects(db.query("select messaging_request_context('imessage','admin@example.com')"),/permission denied/);
 } finally {await db.close();}
});
