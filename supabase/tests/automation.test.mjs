import assert from 'node:assert/strict';
import { readFile,readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';
const folder=new URL('../migrations/',import.meta.url);
const migrations=await Promise.all((await readdir(folder)).filter(n=>n.endsWith('.sql')).sort().map(n=>readFile(new URL(n,folder),'utf8')));
const admin='11111111-1111-4111-8111-111111111111', member='22222222-2222-4222-8222-222222222222';
async function setup() {
 const db=new PGlite();
 await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
 create schema auth; grant usage on schema public,auth to anon,authenticated,service_role;
 create function auth.uid() returns uuid language sql as $$ select null::uuid $$;
 create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,encrypted_password text,raw_user_meta_data jsonb default '{}');`);
 for(const sql of migrations) await db.exec(sql);
 for(const [code,id,name] of [['ADMIN',admin,'Admin'],['ONE',member,'Ada One']]) {
  await db.query('insert into members(code,display_name,board_role,email,contact_consent) values($1,$2,$3,$4,true)',[code,name,'Member',code.toLowerCase()+'@example.com']);
  await db.query("insert into auth.users(id,email,email_confirmed_at,encrypted_password) values($1,$2,now(),'synthetic')",[id,code.toLowerCase()+'@example.com']);
  await db.query("insert into member_identities(platform,sender_id,member_code,reminders_enabled) values('imessage',$1,$2,true)",[code.toLowerCase()+'@example.com',code]);
 }
 await db.exec("insert into members(code,display_name,board_role,email,contact_consent) values('TWO','Ada Two','Member','two@example.com',true)");
 await db.exec("insert into member_identities(platform,sender_id,member_code,reminders_enabled) values('imessage','two@example.com','TWO',true)");
 await db.query('update profiles set is_admin=true where id=$1',[admin]);
 await db.exec("insert into member_aliases(semester_code,alias,member_code) values('fall-2026','Ada One','ONE'),('fall-2026','Ada Two','TWO')");
 await db.exec('set role service_role');
 return db;
}
async function task(db,owner='ONE',text='Ada One',due='2020-01-01') {
 return (await db.query("insert into tasks(title,month_code,semester_code,owner_code,assignee_text,due_date) values('Synthetic task','2026-11','fall-2026',$1,$2,$3) returning *",[owner,text,due])).rows[0];
}
async function midday(db) {return (await db.query("select (date_trunc('day',now() at time zone 'America/New_York')+interval '12 hours') at time zone 'America/New_York' stamp")).rows[0].stamp;}
async function claim(db,stamp=null) {return (await db.query("select claim_task_notification('fall-2026','America/New_York',$1) n",[stamp||await midday(db)])).rows[0].n;}
async function count(db,kind) {return Number((await db.query('select count(*) n from task_notifications where kind=$1',[kind])).rows[0].n);}

test('initial assignments resolve whole co-owner aliases; unknown and ambiguous cells fail closed',async()=>{
 const db=await setup();
 try {
  const shared=await task(db,null,'Ada One and Ada Two');
  assert.deepEqual((await db.query('select task_notification_recipients(t) codes from tasks t where id=$1',[shared.id])).rows[0].codes,['ONE','TWO']);
  assert.equal(await count(db,'assignment'),2);
  await task(db,null,'Ada One and Unknown'); assert.equal(await count(db,'assignment'),2);
  await db.exec("insert into member_aliases(semester_code,alias,member_code) values('fall-2026','Ada One and Ada Two','ADMIN')");
  const ambiguous=await task(db,null,'Ada One and Ada Two');
  assert.equal((await db.query('select task_notification_recipients(t) codes from tasks t where id=$1',[ambiguous.id])).rows[0].codes,null);
 } finally {await db.close();}
});

test('nudge is administrator-only, daily-deduped and revalidates consent/ownership before sending',async()=>{
 const db=await setup();
 try {
  const t=await task(db); await db.exec("update task_notifications set status='cancelled'");
  await assert.rejects(db.query("select nudge_task($1,$2,'fall-2026')",[member,t.id]),/Administrator required/);
  const queued=(await db.query("select nudge_task($1,$2,'fall-2026') result",[admin,t.id])).rows[0].result;
  assert.equal(queued.queued,1);
  assert.equal((await db.query("select nudge_task($1,$2,'fall-2026') result",[admin,t.id])).rows[0].result.already_requested,true);
  await db.exec("update member_identities set reminders_enabled=false where member_code='ONE'");
  assert.equal(await claim(db),null);
  await db.exec("update member_identities set reminders_enabled=true where member_code='ONE'");
  const notice=await claim(db); assert.equal(notice.recipient,'one@example.com'); assert.match(notice.text,/Admin nudge/);
  await db.query("select finish_task_notification($1,$2,'uncertain',null)",[notice.id,notice.claim_token]);
  assert.equal(await claim(db),null,'uncertain sends are never automatically repeated');
  await db.query("update tasks set status='done' where id=$1",[t.id]);
  await assert.rejects(db.query("select nudge_task($1,$2,'fall-2026')",[admin,t.id]),/unfinished/);
 } finally {await db.close();}
});

test('completion queues only dependent owners after every prerequisite; reopen invalidates stale readiness',async()=>{
 const db=await setup();
 try {
  const a=await task(db), b=await task(db), child=await task(db,'TWO','Ada Two');
  await db.query('insert into task_dependencies(task_id,depends_on_id) values($1,$2),($1,$3)',[child.id,a.id,b.id]);
  await db.query("update tasks set status='done' where id=$1",[a.id]); assert.equal(await count(db,'dependency'),0);
  await db.query("update tasks set status='done' where id=$1",[b.id]); assert.equal(await count(db,'dependency'),1);
  assert.equal((await db.query("select recipient_code from task_notifications where kind='dependency'")).rows[0].recipient_code,'TWO');
  await db.query("select scan_task_notifications('fall-2026','America/New_York',false)"); assert.equal(await count(db,'dependency'),1);
  await db.query("update tasks set status='todo' where id=$1",[b.id]);
  await db.query("update tasks set status='done' where id=$1",[b.id]);
  await db.exec("update task_notifications set status='cancelled' where kind='assignment'");
  const notice=await claim(db); assert.match(notice.text,/Prerequisites complete/); assert.equal(notice.recipient,'two@example.com');
  await db.query("select finish_task_notification($1,$2,'sent','provider')",[notice.id,notice.claim_token]);
  assert.equal(await claim(db),null,'older readiness versions must not also be sent');
 } finally {await db.close();}
});

test('an unsent nudge can be refreshed after a deadline change, but a sent nudge cannot repeat',async()=>{
 const db=await setup();
 try {
  const t=await task(db); await db.exec("update task_notifications set status='cancelled'");
  const nudge=async()=> (await db.query("select nudge_task($1,$2,'fall-2026') result",[admin,t.id])).rows[0].result;
  assert.equal((await nudge()).queued,1);
  await db.query("update tasks set due_date='2027-02-01' where id=$1",[t.id]);
  await claim(db); // Cancels the obsolete snapshot before a replacement is requested.
  assert.equal((await nudge()).queued,1,'refresh the unsent cancelled snapshot');
  const notice=await claim(db);
  assert.ok(notice); assert.match(notice.text,/2027-02-01/);
  await db.query("select finish_task_notification($1,$2,'sent','provider')",[notice.id,notice.claim_token]);
  await db.query("update tasks set due_date='2027-02-02' where id=$1",[t.id]);
  assert.equal((await nudge()).already_requested,true);
  assert.equal(await claim(db),null);
 } finally {await db.close();}
});

test('a shared-task nudge queues only opted-in recipients and defers until notification hours',async()=>{
 const db=await setup();
 try {
  const t=await task(db,null,'Ada One and Ada Two');
  await db.exec("update task_notifications set status='cancelled'; update member_identities set reminders_enabled=false where member_code='TWO'");
  const queued=(await db.query("select nudge_task($1,$2,'fall-2026') result",[admin,t.id])).rows[0].result;
  assert.equal(queued.queued,1);
  const stamp=await midday(db);
  assert.equal(await claim(db,new Date(stamp.getTime()-12*3600000)),null);
  const notice=await claim(db,stamp);
  assert.equal(notice.recipient,'one@example.com');
  assert.match(notice.text,/Admin nudge/);
 } finally {await db.close();}
});

test('overdue scanning uses local dates, daily dedupe and explicit due time; quiet hours defer sends',async()=>{
 const db=await setup();
 try {
  await task(db); await db.exec("update task_notifications set status='cancelled'");
  const stamp=await midday(db);
  await db.query("select scan_task_notifications('fall-2026','America/New_York',true,$1)",[stamp]);
  const today=stamp.toISOString().slice(0,10);
  const later=await task(db,'TWO','Ada Two',today);
  await db.query("update tasks set due_time='13:00' where id=$1",[later.id]);
  await db.exec("update task_notifications set status='cancelled' where kind='assignment'");
  await db.query("select scan_task_notifications('fall-2026','America/New_York',true,$1)",[stamp]);
  assert.equal(await count(db,'overdue'),1);
  const night=new Date(stamp.getTime()-12*3600000);
  assert.equal(await claim(db,night),null);
  // A separate daytime claim exercises the live formatter without contacting Photon.
  const notice=await claim(db,stamp); assert.match(notice.text,/Overdue reminder/);
 } finally {await db.close();}
});

test('automation leases fence concurrent runners and browser roles cannot access queues',async()=>{
 const db=await setup();
 try {
  const token=(await db.query("select claim_automation_job('sheets:test') token")).rows[0].token;
  assert.ok(token); assert.equal((await db.query("select claim_automation_job('sheets:test') token")).rows[0].token,null);
  assert.equal((await db.query("select finish_automation_job('sheets:test',$1,'conflict','{}') done",[admin])).rows[0].done,false);
  await db.query("select finish_automation_job('sheets:test',$1,'conflict','{\"conflicts\":1}')",[token]);
  assert.ok((await db.query("select claim_automation_job('sheets:test') token")).rows[0].token);
  await db.exec('reset role; set role authenticated');
  await assert.rejects(db.exec('select * from task_notifications'),/permission denied/);
  await assert.rejects(db.exec("select claim_automation_job('sheets:test')"),/permission denied/);
  await assert.rejects(db.query("select nudge_task($1,$2,'fall-2026')",[admin,member]),/permission denied/);
 } finally {await db.close();}
});

test('deadline delivery rechecks canonical owner and contact consent after the legacy queue claim',async()=>{
 const db=await setup();
 try {
  async function queueAndClaim(owner) {
   const t=await task(db,owner,'Ada One','2027-01-20');
   await db.query(`select queue_deadline_reminder($1,'ONE','2027-01-20','seven_day','photon',
    '2027-01-13T14:00Z','2027-01-17T14:00Z','one@example.com','Ada One','Synthetic reminder','2027-01-13T14:01Z')`,[t.id]);
   return (await db.query("select claim_deadline_reminder('photon','2027-01-13T14:01Z') item")).rows[0].item;
  }
  const wrong=await queueAndClaim('TWO');
  assert.ok(wrong);
  assert.equal((await db.query("select begin_deadline_reminder($1,$2,'2027-01-13T14:01Z',true) item",[wrong.id,wrong.claim_token])).rows[0].item,null);
  const revoked=await queueAndClaim('ONE');
  await db.exec("update members set contact_consent=false,email=null,phone_number=null where code='ONE'");
  assert.equal((await db.query("select begin_deadline_reminder($1,$2,'2027-01-13T14:01Z',true) item",[revoked.id,revoked.claim_token])).rows[0].item,null);
 } finally {await db.close();}
});
