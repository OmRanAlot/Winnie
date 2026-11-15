import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';
const folder = new URL('../migrations/', import.meta.url);
const migrations = await Promise.all((await readdir(folder)).filter(n=>n.endsWith('.sql')).sort().map(n=>readFile(new URL(n,folder),'utf8')));
const admin='11111111-1111-4111-8111-111111111111', member='22222222-2222-4222-8222-222222222222';
async function setup() {
 const db=new PGlite();
 await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
 create schema auth; grant usage on schema public,auth to anon,authenticated,service_role;
 create function auth.uid() returns uuid language sql as $$ select null::uuid $$;
 create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,encrypted_password text,raw_user_meta_data jsonb default '{}');`);
 for(const sql of migrations) await db.exec(sql);
 for(const [id,code] of [[admin,'ADMIN'],[member,'OWNER']]) {
  const email=code.toLowerCase()+'@example.com';
  await db.query('insert into members(code,display_name,board_role,email,contact_consent) values($1,$1,$2,$3,true)',[code,'Treasurer',email]);
  await db.query("insert into auth.users(id,email,email_confirmed_at,encrypted_password) values($1,$2,now(),'synthetic')",[id,email]);
 }
 await db.query('update profiles set is_admin=true where id=$1',[admin]);
 await db.exec('set role service_role');
 return db;
}
const payload=()=>({event_name:'Synthetic workshop',event_date:'2027-04-20',semester_code:'spring-2027',plan_text:'Outline',tasks:[
 {id:'materials',title:'List materials',owner_code:'OWNER',due_date:'2027-04-10',dependency_ids:[]},
 {id:'purchase',title:'Purchase materials',owner_code:'OWNER',due_date:'2027-04-11',dependency_ids:['materials']},
]});
async function call(db,action,id=null,revision=null,body={},actor=admin) {
 return (await db.query('select manage_event_plan($1,$2,$3,$4,$5::jsonb) result',[actor,action,id,revision,JSON.stringify(body)])).rows[0].result;
}
async function count(db,table) {return Number((await db.query(`select count(*) n from ${table}`)).rows[0].n);}

test('shared drafts use revisions; approval atomically activates tasks, graph, audit and notices once',async()=>{
 const db=await setup();
 try {
  const draft=await call(db,'create',null,null,payload());
  assert.equal(await count(db,'tasks'),0);
  assert.equal((await call(db,'get',draft.id)).payload.event_name,'Synthetic workshop');
  assert.equal((await call(db,'list')).length,1);
  const edited=await call(db,'update',draft.id,1,{...payload(),event_name:'Reviewed workshop'});
  assert.equal(edited.revision,2);
  await assert.rejects(call(db,'approved',draft.id,1),/Stale revision/);
  const approved=await call(db,'approved',draft.id,2);
  assert.equal(approved.status,'approved'); assert.equal(approved.reviewed_by,admin);
  assert.equal(approved.activated_task_ids.length,2);
  assert.equal(await count(db,'tasks'),2); assert.equal(await count(db,'task_dependencies'),1);
  assert.equal(await count(db,'event_plan_notifications'),2);
  assert.equal(await count(db,'event_plan_reviews'),1);
  assert.deepEqual((await call(db,'approved',draft.id,2)).activated_task_ids,approved.activated_task_ids);
  assert.equal(await count(db,'tasks'),2); assert.equal(await count(db,'event_plan_notifications'),2);
  assert.equal(await count(db,'event_plan_reviews'),1);
  await assert.rejects(call(db,'update',draft.id,2,payload()),/already decided/);
  await assert.rejects(call(db,'rejected',draft.id,2),/already decided/);
  const rows=(await db.query('select owner_code,original_assignee_code,source_plan_id,semester_code from tasks')).rows;
  assert.ok(rows.every(t=>t.owner_code==='OWNER' && t.original_assignee_code==='OWNER' && t.source_plan_id===draft.id && t.semester_code==='spring-2027'));
 } finally {await db.close();}
});

test('rejection creates no tasks; invalid activation rolls back and rechecks current owners',async()=>{
 const db=await setup();
 try {
  let draft=await call(db,'create',null,null,payload());
  assert.equal((await call(db,'rejected',draft.id,1,{note:'Revise scope'})).status,'rejected');
  assert.equal(await count(db,'tasks'),0); assert.equal(await count(db,'event_plan_notifications'),0);
  draft=await call(db,'update',draft.id,1,payload());
  assert.equal(draft.status,'draft'); assert.equal(draft.revision,2);
  await db.exec("update members set active=false where code='OWNER'");
  await assert.rejects(call(db,'approved',draft.id,2),/owners and dates/);
  await db.exec("update members set active=true where code='OWNER'");
  const invalid=payload(); invalid.tasks[1].dependency_ids=['missing'];
  draft=await call(db,'update',draft.id,2,invalid);
  await assert.rejects(call(db,'approved',draft.id,3),/dependency/);
  const cycle=payload(); cycle.tasks[0].dependency_ids=['purchase']; cycle.tasks[0].due_date='2027-04-11';
  draft=await call(db,'update',draft.id,3,cycle);
  await assert.rejects(call(db,'approved',draft.id,4),/cycle/);
  assert.equal(await count(db,'tasks'),0); assert.equal(await count(db,'event_plan_notifications'),0);
  assert.equal((await call(db,'get',draft.id)).status,'draft');
  const lateFailure=payload(); lateFailure.tasks[1].title='x'.repeat(201);
  draft=await call(db,'update',draft.id,4,lateFailure);
  await assert.rejects(call(db,'approved',draft.id,5),/check constraint/);
  assert.equal(await count(db,'tasks'),0); assert.equal(await count(db,'event_plan_notifications'),0);
  assert.equal(await count(db,'event_plan_reviews'),1,'only the original rejection audit survives failed approvals');
 } finally {await db.close();}
});

test('ordinary accounts and browser database callers cannot bypass administrator review',async()=>{
 const db=await setup();
 try {
  await assert.rejects(call(db,'create',null,null,payload(),member),/Administrator required/);
  await db.exec('reset role; set role authenticated');
  await assert.rejects(call(db,'create',null,null,payload()),/permission denied/);
  await assert.rejects(db.exec('select * from event_plans'),/permission denied/);
  await assert.rejects(db.exec('select * from event_plan_notifications'),/permission denied/);
  await assert.rejects(db.exec('select * from event_plan_reviews'),/permission denied/);
  await assert.rejects(db.exec('select claim_event_plan_notification()'),/permission denied/);
  await db.exec('reset role; set role service_role');
  await db.exec("update members set active=false where code='ADMIN'");
  await assert.rejects(call(db,'list'),/Administrator required/);
 } finally {await db.close();}
});

test('assignment notices require opt-in and current ownership and never repeat uncertain sends',async()=>{
 const db=await setup();
 try {
  const body=payload(); body.tasks=body.tasks.slice(0,1);
  const draft=await call(db,'create',null,null,body);
  const approved=await call(db,'approved',draft.id,1);
  assert.equal((await db.query('select claim_event_plan_notification() n')).rows[0].n,null);
  await db.query("insert into member_identities(platform,sender_id,member_code,reminders_enabled) values('imessage','+15555550123','OWNER',true)");
  const notice=(await db.query('select claim_event_plan_notification() n')).rows[0].n;
  assert.equal(notice.recipient,'+15555550123'); assert.match(notice.text,/New assignment/);
  assert.equal((await db.query('select claim_event_plan_notification() n')).rows[0].n,null);
  await db.query("select finish_event_plan_notification($1,$2,'uncertain',null)",[notice.id,notice.claim_token]);
  assert.equal((await db.query('select claim_event_plan_notification() n')).rows[0].n,null);
  const second=await call(db,'create',null,null,body);
  const secondApproval=await call(db,'approved',second.id,1);
  await db.query("update tasks set owner_code='ADMIN' where id=$1",[secondApproval.activated_task_ids[0]]);
  assert.equal((await db.query('select claim_event_plan_notification() n')).rows[0].n,null);
  assert.equal((await db.query('select status from event_plan_notifications where plan_id=$1',[second.id])).rows[0].status,'cancelled');
  assert.equal(approved.activated_task_ids.length,1);
 } finally {await db.close();}
});
