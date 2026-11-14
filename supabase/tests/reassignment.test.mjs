import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

const ids = Object.fromEntries(['member', 'other', 'pres', 'vp', 'admin'].map((name, i) =>
  [name, `00000000-0000-4000-8000-00000000000${i + 1}`]));
const migration = await readFile(new URL('../migrations/20261114160001_task_original_assignee_and_requests.sql', import.meta.url), 'utf8');

async function database() {
  const db = new PGlite();
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth;
    grant usage on schema public, auth to anon, authenticated, service_role;
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
    $$;
    create table auth.users (id uuid primary key, email text, email_confirmed_at timestamptz,
      raw_user_meta_data jsonb default '{}');
  `);
  for (const name of ['20261114080000_create_tasks.sql', '20261114100000_add_tracker_context.sql',
    '20261114120000_add_messaging_members.sql', '20261114120000_create_profiles.sql',
    '20261114140000_link_member_roster.sql']) {
    await db.exec(await readFile(new URL(`../migrations/${name}`, import.meta.url), 'utf8'));
  }
  for (const [name, id] of Object.entries(ids)) {
    const role = name === 'pres' ? 'President' : name === 'vp' ? 'Vice President' : 'member';
    await db.query('insert into public.members(code, display_name, board_role) values ($1,$2,$3)',
      [name.toUpperCase(), `${name} Example`, role]);
    await db.query('insert into auth.users(id) values ($1)', [id]);
    await db.query('update public.profiles set member_code=$1, is_admin=$2 where id=$3',
      [name === 'admin' ? null : name.toUpperCase(), name === 'admin', id]);
  }
  await db.exec(`insert into public.member_aliases values ('fall-2026', 'ME', 'MEMBER')`);
  await db.exec(`insert into public.tasks(title,month_code,semester_code,assignee_text)
    values ('Legacy single','2026-11','fall-2026','ME'),
           ('Legacy multiple','2026-11','fall-2026','ME, Other')`);
  await db.exec(migration);
  return db;
}
async function asUser(db, name) {
  await db.exec('reset role');
  await db.query("select set_config('request.jwt.claim.sub', $1, false)", [ids[name] ?? '']);
  await db.exec('set role authenticated');
}
async function newTask(db, owner = 'MEMBER') {
  await db.exec('reset role');
  return (await db.query(`insert into public.tasks(title,month_code,owner_code,assignee_text)
    values ('Synthetic task','2026-11',$1,$2) returning *`, [owner, owner ? 'member Example' : ''])).rows[0];
}
async function submit(db, task, who = 'member', target = 'OTHER') {
  await asUser(db, who);
  return (await db.query('select * from public.submit_task_reassignment($1,$2,$3)',
    [task.id, target, 'Schedule conflict'])).rows[0];
}
async function review(db, request, who, decision = 'approved') {
  await asUser(db, who);
  return (await db.query('select * from public.review_task_reassignment($1,$2,$3)',
    [request.id, decision, 'Reviewed'])).rows[0];
}

test('original code backfills exact aliases, preserves ambiguity, and survives reassignment', async () => {
  const db = await database();
  try {
    const legacy = (await db.query('select title,original_assignee_code from tasks order by title')).rows;
    assert.deepEqual(legacy, [
      {title: 'Legacy multiple', original_assignee_code: null},
      {title: 'Legacy single', original_assignee_code: 'MEMBER'},
    ]);
    const task = await newTask(db);
    assert.equal(task.original_assignee_code, 'MEMBER');
    await db.query("update tasks set owner_code='OTHER' where id=$1", [task.id]);
    assert.equal((await db.query('select original_assignee_code from tasks where id=$1', [task.id])).rows[0].original_assignee_code, 'MEMBER');
    await assert.rejects(db.query("update tasks set original_assignee_code='OTHER' where id=$1", [task.id]), /cannot be changed/);
    const unassigned = await newTask(db, null);
    await db.query("update tasks set owner_code='OTHER' where id=$1", [unassigned.id]);
    assert.equal((await db.query('select original_assignee_code from tasks where id=$1', [unassigned.id])).rows[0].original_assignee_code, 'OTHER');
  } finally { await db.close(); }
});

test('member submits; only president, VP, or admin can approve atomically', async () => {
  const db = await database();
  try {
    for (const reviewer of ['pres', 'vp', 'admin']) {
      const task = await newTask(db);
      const request = await submit(db, task);
      assert.equal(request.requester_code, 'MEMBER');
      assert.equal(request.status, 'pending');
      await assert.rejects(review(db, request, 'member'), /Only the president/);
      const approved = await review(db, request, reviewer);
      assert.equal(approved.status, 'approved');
      assert.equal(approved.reviewed_by_profile_id, ids[reviewer]);
      assert.ok(approved.reviewed_at);
      assert.equal((await db.query('select * from pending_task_requests')).rows.length, 0);
      await db.exec('reset role');
      const saved = (await db.query('select * from tasks where id=$1', [task.id])).rows[0];
      assert.equal(saved.owner_code, 'OTHER');
      assert.equal(saved.assignee_text, 'other Example');
      assert.equal(saved.original_assignee_code, 'MEMBER');
      await assert.rejects(review(db, request, reviewer), /Pending request not found/);
    }
  } finally { await db.close(); }
});

test('RLS hides others requests; direct writes and anonymous RPCs are denied', async () => {
  const db = await database();
  try {
    const task = await newTask(db);
    const request = await submit(db, task);
    assert.equal((await db.query('select * from pending_task_requests')).rows.length, 1);
    await assert.rejects(db.query("update task_reassignment_requests set status='approved' where id=$1", [request.id]), /permission denied/);
    await assert.rejects(submit(db, task), /duplicate key/);
    await asUser(db, 'other');
    assert.equal((await db.query('select * from pending_task_requests')).rows.length, 0);
    await asUser(db, 'pres');
    assert.equal((await db.query('select * from pending_task_requests')).rows.length, 1);
    await db.exec('reset role; set role anon');
    await assert.rejects(db.query('select * from pending_task_requests'), /permission denied/);
    await assert.rejects(db.query('select * from submit_task_reassignment($1,$2)', [task.id, 'OTHER']), /permission denied/);
    await asUser(db, 'unknown');
    await assert.rejects(db.query('select * from submit_task_reassignment($1,$2)', [task.id, 'OTHER']), /authenticated active member/);
  } finally { await db.close(); }
});

test('reject preserves assignment; stale approval rolls back; completed tasks cannot be reassigned', async () => {
  const db = await database();
  try {
    const task = await newTask(db);
    const request = await submit(db, task);
    await review(db, request, 'vp', 'rejected');
    await db.exec('reset role');
    assert.equal((await db.query('select owner_code from tasks where id=$1', [task.id])).rows[0].owner_code, 'MEMBER');
    const stale = await submit(db, task);
    await db.exec('reset role');
    await db.query("update tasks set owner_code='PRES' where id=$1", [task.id]);
    await assert.rejects(review(db, stale, 'admin'), /assignment changed/);
    assert.equal((await db.query('select status from task_reassignment_requests where id=$1', [stale.id])).rows[0].status, 'pending');
    await review(db, stale, 'admin', 'rejected');
    await db.exec('reset role');
    await db.query("update tasks set status='done' where id=$1", [task.id]);
    await assert.rejects(submit(db, task), /Completed tasks/);
  } finally { await db.close(); }
});
