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
async function setup() {
  const db = new PGlite();
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; grant usage on schema public,auth to anon,authenticated,service_role;
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,encrypted_password text,raw_user_meta_data jsonb default '{}');`);
  for (const sql of migrations) await db.exec(sql);
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

test('only verified recipient can respond; acceptance persists without transfer until admin approval',async()=>{
  const {db,task,request} = await setup();
  try {
    await as(db,'OTHER');
    assert.equal((await db.query('select id from task_reassignment_requests')).rows.length,0);
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/Incoming request not found/);
    await as(db,'ADMIN');
    await assert.rejects(db.query('select review_task_reassignment($1,$2)',[request.id,'approved']),/must accept/);
    await as(db,'TARGET');
    assert.equal((await db.query('select id from task_reassignment_requests')).rows.length,1);
    await assert.rejects(db.query("update task_reassignment_requests set recipient_decision='accepted' where id=$1",[request.id]),/permission denied/);
    const accepted=(await db.query('select * from respond_task_reassignment($1,$2)',[request.id,'accepted'])).rows[0];
    assert.equal(accepted.recipient_decision,'accepted'); assert.equal(accepted.responded_by_profile_id,ids.TARGET); assert.ok(accepted.responded_at);
    assert.equal((await owner(db,task.id)).owner_code,'OWNER');
    await as(db,'TARGET');
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'denied']),/already been answered/);
    await assert.rejects(db.query('select review_task_reassignment($1,$2)',[request.id,'approved']),/Only the president/);
    await as(db,'ADMIN');
    await db.query('select review_task_reassignment($1,$2)',[request.id,'approved']);
    assert.deepEqual(await owner(db,task.id),{owner_code:'TARGET',original_assignee_code:'OWNER'});
  } finally { await db.close(); }
});

test('denial closes request and cannot be overridden; anonymous and inactive responses fail',async()=>{
  const {db,task,request} = await setup();
  try {
    await as(db,null);
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/permission denied/);
    await db.exec('reset role'); await db.exec("update members set active=false where code='TARGET'");
    await as(db,'TARGET');
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/verified active/);
    await db.exec('reset role'); await db.exec("update members set active=true where code='TARGET'");
    await as(db,'TARGET');
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'approved']),/accepted or denied/);
    const declined = (await db.query('select * from respond_task_reassignment($1,$2)',[request.id,'denied'])).rows[0];
    assert.equal(declined.status,'declined'); assert.equal(declined.recipient_decision,'denied');
    await as(db,'ADMIN');
    await assert.rejects(db.query('select review_task_reassignment($1,$2)',[request.id,'approved']),/Pending request not found/);
    assert.equal((await owner(db,task.id)).owner_code,'OWNER');
  } finally {await db.close();}
});

test('stale and completed assignments cannot be accepted and stale approvals roll back',async()=>{
  const {db,task,request} = await setup();
  try {
    await db.exec('reset role'); await db.query("update tasks set status='done' where id=$1",[task.id]);
    await as(db,'TARGET');
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/Completed tasks/);
    await db.exec('reset role'); await db.query("update tasks set status='todo',owner_code='OTHER' where id=$1",[task.id]);
    await as(db,'TARGET');
    await assert.rejects(db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']),/assignment changed/);
    await db.exec('reset role'); await db.query("update tasks set owner_code='OWNER' where id=$1",[task.id]);
    await as(db,'TARGET'); await db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']);
    await db.exec('reset role'); await db.query("update tasks set owner_code='OTHER' where id=$1",[task.id]);
    await as(db,'ADMIN');
    await assert.rejects(db.query('select review_task_reassignment($1,$2)',[request.id,'approved']),/assignment changed/);
    assert.equal((await db.query('select status from task_reassignment_requests where id=$1',[request.id])).rows[0].status,'pending');
  } finally {await db.close();}
});

async function photon(db,code,event,action,payload={}) {
  await db.exec('reset role; set role service_role');
  return (await db.query('select messaging_reassignment($1,$2,$3,$4,$5::jsonb) as result',
    ['imessage',code.toLowerCase()+'@example.com',event,action,JSON.stringify(payload)])).rows[0].result;
}
async function identities(db) {
  await db.exec('reset role');
  for (const code of Object.keys(ids)) await db.query("insert into member_identities(platform,sender_id,member_code,reminders_enabled) values('imessage',$1,$2,true)",[code.toLowerCase()+'@example.com',code]);
}

test('Photon acceptance and browser approval share one request; retries cannot repeat or forge decisions',async()=>{
  const {db,task,request}=await setup();
  try {
    await identities(db);
    await assert.rejects(photon(db,'OWNER','bad-accept','accepted',{request_no:request.request_no}),/Incoming request not found/);
    await assert.rejects(photon(db,'ADMIN','early-approval','approved',{request_no:request.request_no}),/must accept/);
    const result=await photon(db,'TARGET','accept-once','accepted',{request_no:request.request_no});
    assert.equal(result.recipient_decision,'accepted');
    assert.deepEqual(await photon(db,'TARGET','accept-once','accepted',{request_no:request.request_no}),result);
    await assert.rejects(photon(db,'TARGET','accept-once','denied',{request_no:request.request_no}),/content changed/);
    assert.equal((await owner(db,task.id)).owner_code,'OWNER');
    await as(db,'OWNER');
    assert.equal((await db.query('select recipient_decision from task_reassignment_requests where id=$1',[request.id])).rows[0].recipient_decision,'accepted');
    await as(db,'ADMIN'); await db.query('select review_task_reassignment($1,$2)',[request.id,'approved']);
    assert.equal((await owner(db,task.id)).owner_code,'TARGET');
    await db.exec('set role service_role');
    assert.equal((await db.query("select count(*)::int n from reassignment_notifications where event='decision'")).rows[0].n,2);
  } finally {await db.close();}
});

test('Photon uses the app admin flag; notifications are claimed once and uncertain sends are not retried',async()=>{
  const {db,request}=await setup();
  try {
    await identities(db); await db.exec('set role service_role');
    const notice=(await db.query('select claim_reassignment_notification() n')).rows[0].n;
    assert.equal(notice.kind,'dm'); assert.equal(notice.recipient,'target@example.com'); assert.match(notice.text,/accept REQ-/);
    assert.equal((await db.query('select claim_reassignment_notification() n')).rows[0].n,null);
    assert.equal((await db.query('select finish_reassignment_notification($1,$2,$3,$4) result',[notice.id,notice.claim_token,'uncertain',null])).rows[0].result,'uncertain');
    assert.equal((await db.query('select claim_reassignment_notification() n')).rows[0].n,null);
    await as(db,'TARGET'); await db.query('select respond_task_reassignment($1,$2)',[request.id,'accepted']);
    await assert.rejects(photon(db,'OWNER','not-admin','approved',{request_no:request.request_no}),/Only the president/);
    const approved=await photon(db,'ADMIN','app-admin','approved',{request_no:request.request_no});
    assert.equal(approved.status,'approved');
    await db.exec('reset role');
    assert.equal((await db.query("select messaging_admin from members where code='ADMIN'")).rows[0].messaging_admin,false);
    await as(db,'TARGET');
    await assert.rejects(db.query('select messaging_reassignment($1,$2,$3,$4,$5::jsonb)',['imessage','admin@example.com','forged','approved','{}']),/permission denied/);
  } finally {await db.close();}
});

test('saved Gemini candidate selection links HELP to the shared queue and blocks legacy approval',async()=>{
  const {db,task,request}=await setup();
  try {
    await identities(db); await db.exec('reset role');
    const h=(await db.query(`insert into task_help_requests(task_id,requester_code,task_version,status,candidates)
      select id,'OWNER',updated_at,'suggestions_ready','[{"code":"TARGET","name":"Target"}]'::jsonb from tasks where id=$1 returning *`,[task.id])).rows[0];
    await db.exec('set role service_role');
    const reply=(await db.query("select help_transition($1,$2,'select','OWNER','[]','TARGET',null) result",[h.request_no,h.revision])).rows[0].result.reply;
    assert.match(reply,/recipient must accept/);
    assert.equal((await db.query('select reassignment_id from task_help_requests where request_no=$1',[h.request_no])).rows[0].reassignment_id,request.id);
    assert.equal((await db.query('select count(*)::int n from task_reassignment_requests')).rows[0].n,1);
    await assert.rejects(db.query("select help_transition($1,$2,'approve',null,'[]',null,'TARGET')",[h.request_no,h.revision+1]),/Legacy approval is disabled/);
    await assert.rejects(db.query("select help_transition_legacy($1,$2,'approve',null,'[]',null,'TARGET')",[h.request_no,h.revision+1]),/permission denied/);
    const listed=await photon(db,'TARGET','list-incoming','list');
    assert.equal(listed.requests[0].request_no,request.request_no);
    const denied=await photon(db,'TARGET','decline','denied',{request_no:request.request_no});
    assert.equal(denied.status,'declined');
    assert.equal((await owner(db,task.id)).owner_code,'OWNER');
  } finally {await db.close();}
});
