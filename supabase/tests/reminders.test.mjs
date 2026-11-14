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
