// Run the real completion transaction using synthetic people/tasks in local PostgreSQL.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { PGlite } from "@electric-sql/pglite";

const taskId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const migrations = await Promise.all([
  "20261114080000_create_tasks.sql",
  "20261114100000_add_tracker_context.sql",
  "20261114120000_add_messaging_members.sql",
  "20261114160000_message_task_completions.sql",
].map(name => readFile(new URL(`../migrations/${name}`, import.meta.url), "utf8")));

async function database() {
  const db = new PGlite();
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    grant usage on schema public to anon, authenticated, service_role;
  `);
  for (const sql of migrations) await db.exec(sql);
  await db.exec(`
    insert into public.members(code,display_name) values ('DEMO','Demo member');
    insert into public.member_identities(platform,sender_id,member_code)
      values ('imessage','+15555550123','DEMO');
    insert into public.tasks(id,title,month_code,semester_code,assignee_text) values
      ('${taskId}','Book room','2026-10','fall-2026','Demo member'),
      ('${secondId}','Make flyer','2026-10','fall-2026','Demo member');
  `);
  return db;
}

async function current(db, id = taskId) {
  return (await db.query(
    "select status, updated_at::text as version from public.tasks where id=$1", [id],
  )).rows[0];
}

async function complete(db, version, changes = {}) {
  const opts = {
    event: "photon-event-1", sender: "+15555550123", member: "DEMO", hash: "a".repeat(64),
    id: taskId, assignment: "Demo member", semester: "fall-2026", ...changes,
  };
  return (await db.query(`select public.complete_task_from_message(
    'imessage',$1,$2,$3,$4,$5,$6,$7,$8) as result`, [
    opts.event, opts.sender, opts.member, opts.hash, opts.id, version, opts.assignment, opts.semester,
  ])).rows[0].result;
}

test("completion and receipt commit together; replay cannot complete a different task", async () => {
  const db = await database();
  try {
    const before = await current(db);
    const first = await complete(db, before.version);
    assert.equal(first.changed, true);
    assert.equal(first.replayed, false);
    assert.match(first.reply, /Marked "Book room"/);
    const saved = await current(db);
    assert.equal(saved.status, "done");
    const replay = await complete(db, before.version, { id: secondId });
    assert.equal(replay.replayed, true);
    assert.equal(replay.reply, first.reply);
    assert.deepEqual(await current(db), saved);
    assert.equal((await current(db, secondId)).status, "todo");
    assert.equal((await db.query("select count(*)::int as n from public.message_task_completions")).rows[0].n, 1);
    await assert.rejects(complete(db, before.version, { hash: "b".repeat(64) }), /payload changed/);
  } finally { await db.close(); }
});

test("stale assignments, wrong semester, unknown and inactive senders are rejected", async () => {
  const db = await database();
  try {
    const before = await current(db);
    await assert.rejects(complete(db, before.version, { assignment: "Other member" }), /Task changed/);
    await assert.rejects(complete(db, before.version, { semester: "spring-2027" }), /unavailable/);
    await assert.rejects(complete(db, before.version, { sender: "+15555550999" }), /not active/);
    await db.exec("update public.members set active=false where code='DEMO'");
    await assert.rejects(complete(db, before.version), /not active/);
    assert.equal((await current(db)).status, "todo");
    assert.equal((await db.query("select count(*)::int as n from public.message_task_completions")).rows[0].n, 0);
  } finally { await db.close(); }
});

test("receipt failure rolls back the status change; repeated completion is a no-op", async () => {
  const db = await database();
  try {
    const before = await current(db);
    await assert.rejects(complete(db, before.version, { hash: "invalid" }), /check constraint/);
    assert.equal((await current(db)).status, "todo");
    await complete(db, before.version);
    const saved = await current(db);
    const second = await complete(db, saved.version, { event: "photon-event-2" });
    assert.equal(second.changed, false);
    assert.match(second.reply, /already done/);
    assert.deepEqual(await current(db), saved);
  } finally { await db.close(); }
});

test("browser accounts cannot read receipts or invoke the completion function", async () => {
  const db = await database();
  try {
    const before = await current(db);
    await db.exec("set role authenticated");
    await assert.rejects(db.query("select * from public.message_task_completions"), /permission denied/);
    await assert.rejects(complete(db, before.version), /permission denied/);
  } finally { await db.close(); }
});
