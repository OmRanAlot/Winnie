// Real reminder SQL, synthetic recipients, no network/Photon calls.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { PGlite } from "@electric-sql/pglite";

const taskId = "11111111-1111-4111-8111-111111111111";
const now = "2027-01-13T14:01:00Z";
const migrations = await Promise.all([
  "20261114080000_create_tasks.sql", "20261114100000_add_tracker_context.sql",
  "20261114120000_add_messaging_members.sql", "20261114160000_message_task_completions.sql",
  "20261114180000_deadline_reminders.sql",
  "20261114190000_help_checkin_schedule.sql",
  "20261114200000_help_handoffs.sql",
].map(name => readFile(new URL(`../migrations/${name}`, import.meta.url), "utf8")));

async function database() {
  const db = new PGlite();
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    grant usage on schema public to anon,authenticated,service_role;
  `);
  for (const migration of migrations) await db.exec(migration);
  await db.exec(`
    insert into public.members(code,display_name) values ('ONE','Demo One');
    insert into public.member_identities(platform,sender_id,member_code,reminders_enabled)
      values ('imessage','+15555550123','ONE',true);
    insert into public.tasks(id,title,month_code,due_date,assignee_text,semester_code,
        created_at,reminder_schedule_started_at) values
      ('${taskId}','Book room','2027-01','2027-01-20','Demo One','spring-2027',
       '2026-01-01T00:00Z','2026-01-01T00:00Z');
  `);
  return db;
}

async function queue(db, transport="photon") {
  return (await db.query(`select public.queue_deadline_reminder(
    $1,'ONE','2027-01-20','seven_day',$2,'2027-01-13T14:00Z','2027-01-17T14:00Z',
    '+15555550123','Demo One','Synthetic reminder',$3) as id`, [taskId,transport,now])).rows[0].id;
}
async function claim(db, stamp=now, transport="photon") {
  return (await db.query("select public.claim_deadline_reminder($1,$2) as item", [transport,stamp])).rows[0].item;
}
async function begin(db, item, verified=true, stamp=now) {
  return (await db.query("select public.begin_deadline_reminder($1,$2,$3,$4) as item",
    [item.id,item.claim_token,stamp,verified])).rows[0].item;
}
async function finish(db, item, outcome="sent", providerId="provider-1") {
  return (await db.query("select public.finish_deadline_reminder($1,$2,$3,$4,$5) as status",
    [item.id,item.claim_token,outcome,providerId,now])).rows[0].status;
}
async function status(db, id) {
  return (await db.query("select status,reason from public.reminder_deliveries where id=$1",[id])).rows[0];
}

async function helpRequest(db, event="help-1") {
  const task = (await db.query("select * from public.tasks where id=$1",[taskId])).rows[0];
  return (await db.query(`select public.request_task_help('imessage',$1,'+15555550123','ONE',$2,
    $3,$4,'Demo One','spring-2027') as result`,[event,"a".repeat(64),taskId,task.updated_at])).rows[0].result;
}
async function transition(db, number, action, actor="ONE", revision=1, selected=null, assignee=null) {
  const candidates = JSON.stringify([{code:"TWO",name:"Demo Two",reason:"Relevant skills",open:1}]);
  return (await db.query(`select public.help_transition($1,$2,$3,$4,$5,$6,$7) as result`,
    [number,revision,action,actor,candidates,selected,assignee])).rows[0].result;
}
async function helpPeople(db) {
  await db.exec(`insert into public.members(code,display_name,messaging_admin) values
   ('TWO','Demo Two',false),('ADMIN','Demo Admin',true);
   insert into public.member_identities(platform,sender_id,member_code,reminders_enabled) values
   ('imessage','+15555550124','TWO',true),('imessage','+15555550125','ADMIN',true);`);
}

test("help requests deduplicate event and repeated requests, and only an admin transfers ownership", async () => {
 const db=await database();
 try {
  await helpPeople(db);
  const request=await helpRequest(db);
  assert.equal((await helpRequest(db)).replayed,true);
  assert.equal((await helpRequest(db,"help-2")).request_no,request.request_no);
  await transition(db,request.request_no,"candidates");
  await transition(db,request.request_no,"select","ONE",1,"TWO");
  assert.equal((await db.query("select assignee_text from tasks where id=$1",[taskId])).rows[0].assignee_text,"Demo One");
  await assert.rejects(transition(db,request.request_no,"approve","ONE",2,null,"Demo Two"),/Not a messaging admin/);
  await assert.rejects(transition(db,request.request_no,"approve","ADMIN",1,null,"Demo Two"),/Request changed/);
  await transition(db,request.request_no,"approve","ADMIN",2,null,"Demo Two");
  assert.equal((await db.query("select assignee_text from tasks where id=$1",[taskId])).rows[0].assignee_text,"Demo Two");
  assert.equal((await db.query("select status from task_help_requests")).rows[0].status,"approved_group_pending");
  await assert.rejects(transition(db,request.request_no,"approve","ADMIN",2,null,"Demo Two"),/Task or request changed/);
 } finally {await db.close();}
});

test("new reminder kinds are accepted and stale tasks invalidate pending help requests",async()=>{
 const db=await database();
 try {
  for(const kind of ["fourteen_day","five_day_help"]) {
   await db.query(`select queue_deadline_reminder($1,'ONE','2027-01-20',$2,'mock',
    '2027-01-01T14:00Z','2027-01-19T14:00Z','+15555550123','Demo One','Test',$3)`,[taskId,kind,now]);
  }
  await helpRequest(db);
  await db.exec("update tasks set due_date='2027-01-21'");
  assert.equal((await db.query("select status from task_help_requests")).rows[0].status,"cancelled");
 }finally{await db.close();}
});

test("admin texts deduplicate and shared-number mode leaves group creation pending",async()=>{
 const db=await database();
 try {
  await helpPeople(db);
  const r=await helpRequest(db);
  await transition(db,r.request_no,"candidates");
  await transition(db,r.request_no,"select","ONE",1,"TWO");
  const item=(await db.query("select claim_help_notification(false) as item")).rows[0].item;
  assert.equal(item.recipient,"+15555550125");
  assert.match(item.text,/approve HELP-1 v2/);
  assert.equal((await db.query("select claim_help_notification(false) as item")).rows[0].item,null);
  await db.query("select finish_help_notification($1,$2,'sent','admin-text-1')",[item.id,item.claim_token]);
  await transition(db,r.request_no,"approve","ADMIN",2,null,"Demo Two");
  const decision=(await db.query("select claim_help_notification(false) as item")).rows[0].item;
  assert.equal(decision.kind,"dm");
  await db.query("select finish_help_notification($1,$2,'sent','decision-text')",[decision.id,decision.claim_token]);
  const newOwner=(await db.query("select claim_help_notification(false) as item")).rows[0].item;
  assert.equal(newOwner.kind,"dm");
  assert.deepEqual(new Set([decision.recipient,newOwner.recipient]),new Set(['+15555550123','+15555550124']));
  await db.query("select finish_help_notification($1,$2,'sent','new-owner-text')",[newOwner.id,newOwner.claim_token]);
  assert.equal((await db.query("select claim_help_notification(false) as item")).rows[0].item,null);
  const group=(await db.query("select claim_help_notification(true) as item")).rows[0].item;
  assert.equal(group.kind,"group");
  await assert.rejects(db.query("select finish_help_notification($1,$2,'sent','group-123')",[group.id,group.claim_token]),/must be bound/);
  await db.query("select bind_help_group($1,$2,'group-123')",[group.id,group.claim_token]);
  await db.query("select bind_help_group($1,$2,'group-123')",[group.id,group.claim_token]);
  await db.query("select finish_help_notification($1,$2,'sent','group-123')",[group.id,group.claim_token]);
  await db.query("select finish_help_notification($1,$2,'sent','group-123')",[group.id,group.claim_token]);
  assert.equal((await db.query("select group_id from task_help_requests")).rows[0].group_id,"group-123");
  await db.query("select report_help_group(1,'imessage','update-1','TWO','Waiting for room confirmation')");
  await db.query("select report_help_group(1,'imessage','update-1','TWO','Waiting for room confirmation')");
  assert.equal((await db.query("select count(*)::int n from help_notifications where dedupe_key like 'update:%'")).rows[0].n,1);
  await assert.rejects(db.query("select report_help_group(1,'imessage','foreign','ADMIN','Nope')"),/Not a handoff participant/);
  await db.exec("update tasks set status='done'; update tasks set status='done'");
  assert.equal((await db.query("select count(*)::int n from help_notifications where dedupe_key='completed:1:ADMIN'")).rows[0].n,1);
 }finally{await db.close();}
});

test("group actions with an uncertain outcome cannot be sent or created twice",async()=>{
 const db=await database();
 try {
  await helpPeople(db); const r=await helpRequest(db);
  await transition(db,r.request_no,"candidates"); await transition(db,r.request_no,"select","ONE",1,"TWO");
  await transition(db,r.request_no,"approve","ADMIN",2,null,"Demo Two");
  await db.exec("update help_notifications set status='cancelled' where kind='dm'");
  const group=(await db.query("select claim_help_notification(true) as item")).rows[0].item;
  await db.query("select finish_help_notification($1,$2,'uncertain',null)",[group.id,group.claim_token]);
  assert.equal((await db.query("select claim_help_notification(true) as item")).rows[0].item,null);
  await db.exec("set role authenticated");
  await assert.rejects(db.query("select claim_help_notification(true)"),/permission denied/);
 }finally{await db.close();}
});

test("repeat scans and competing workers produce one send, including after restart", async () => {
  const db = await database();
  try {
    const id = await queue(db);
    assert.equal(await queue(db),id);
    const claimed = await Promise.all([claim(db),claim(db)]);
    assert.equal(claimed.filter(Boolean).length,1);
    const item = claimed.find(Boolean);
    assert.ok(await begin(db,item));
    assert.equal(await begin(db,item),null);
    assert.equal(await finish(db,item),"sent");
    assert.equal(await finish(db,item),"sent");
    assert.equal(await queue(db),null);
    assert.equal(await claim(db,"2027-01-13T15:00Z"),null);
    assert.equal((await status(db,id)).status,"sent");
    assert.equal((await db.query("select count(*)::int as n from public.reminder_deliveries")).rows[0].n,1);
  } finally { await db.close(); }
});

test("send timeout/crash becomes uncertain and cannot be automatically resent", async () => {
  const db = await database();
  try {
    const id = await queue(db), item = await claim(db);
    await begin(db,item);
    assert.equal(await claim(db,"2027-01-13T14:04Z"),null);
    assert.equal((await status(db,id)).status,"uncertain");
    assert.equal(await queue(db),null);
    assert.equal(await claim(db,"2027-01-13T15:00Z"),null);
    // A delayed successful acknowledgement resolves uncertainty without another send.
    assert.equal(await finish(db,item),"sent");
  } finally { await db.close(); }
});

test("crashes before send can reclaim safely, invalidate old tokens and stop after three claims", async () => {
  const db = await database();
  try {
    const id = await queue(db), first = await claim(db);
    const second = await claim(db,"2027-01-13T14:02:01Z");
    assert.notEqual(first.claim_token,second.claim_token);
    assert.equal(await begin(db,first,true,"2027-01-13T14:02:02Z"),null);
    const third = await claim(db,"2027-01-13T14:03:02Z");
    assert.ok(third);
    assert.equal(await claim(db,"2027-01-13T14:04:03Z"),null);
    assert.equal((await status(db,id)).status,"failed");
  } finally { await db.close(); }
});

test("completion or changed deadline cancels pending deliveries immediately", async () => {
  const db = await database();
  try {
    const id = await queue(db), item = await claim(db);
    await db.exec(`update public.tasks set status='done' where id='${taskId}'`);
    assert.equal((await status(db,id)).status,"cancelled");
    assert.equal(await begin(db,item),null);
    assert.equal(await queue(db),null);
    await db.exec(`update public.tasks set status='todo',due_date='2027-01-21' where id='${taskId}'`);
    assert.equal(await queue(db),null);
    assert.equal(await claim(db),null);
  } finally { await db.close(); }
});

test("revoked identity, inactive member and failed alias check prevent sending", async () => {
  const db = await database();
  try {
    let id = await queue(db), item = await claim(db);
    assert.equal(await begin(db,item,false),null);
    assert.equal((await status(db,id)).status,"cancelled");
    assert.equal(await queue(db),id); // It never reached the provider; safe to requeue after review.
    item = await claim(db);
    await db.exec("update public.member_identities set reminders_enabled=false");
    assert.equal(await begin(db,item),null);
    assert.equal(await queue(db),null);
    await db.exec("update public.member_identities set reminders_enabled=true; update public.members set active=false");
    assert.equal(await queue(db),null);
  } finally { await db.close(); }
});

test("mock and Photon receipts are distinct; expired reminders cannot send", async () => {
  const db = await database();
  try {
    const mockId = await queue(db,"mock"), realId = await queue(db);
    assert.notEqual(mockId,realId);
    const mock = await claim(db,now,"mock");
    await begin(db,mock);
    assert.equal(await finish(db,mock,"mock_sent",null),"mock_sent");
    assert.equal(await claim(db,"2027-01-17T14:00Z"),null);
    assert.equal((await status(db,realId)).status,"cancelled");
  } finally { await db.close(); }
});

test("only one destination per member; ordinary frontend users cannot send reminders", async () => {
  const db = await database();
  try {
    await assert.rejects(db.exec(`insert into public.member_identities
      (platform,sender_id,member_code,reminders_enabled)
      values ('imessage','demo@example.test','ONE',true)`), /unique constraint/);
    await db.exec("set role authenticated");
    await assert.rejects(claim(db), /permission denied/);
    await assert.rejects(db.query("select * from public.reminder_deliveries"), /permission denied/);
  } finally { await db.close(); }
});

test("a conversational completion also cancels its queued reminders in the same transaction", async () => {
  const db = await database();
  try {
    const id = await queue(db);
    const version = (await db.query("select updated_at::text as v from public.tasks where id=$1", [taskId])).rows[0].v;
    const result = (await db.query(`select public.complete_task_from_message(
      'imessage','completion-event','+15555550123','ONE',$1,$2,$3,'Demo One','spring-2027') as r`,
      ["a".repeat(64),taskId,version])).rows[0].r;
    assert.equal(result.changed,true);
    assert.equal((await status(db,id)).status,"cancelled");
    assert.equal(await claim(db),null);
    assert.equal((await db.query("select count(*)::int as n from public.message_task_completions")).rows[0].n,1);
  } finally { await db.close(); }
});
