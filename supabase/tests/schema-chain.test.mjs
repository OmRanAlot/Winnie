// Execute the actual ordered migration chain and both supported task-schema upgrades.
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

const directory = new URL('../migrations/', import.meta.url);
const names = (await readdir(directory)).filter(name => name.endsWith('.sql')).sort();
const sql = Object.fromEntries(await Promise.all(names.map(async name => [
  name, await readFile(new URL(name, directory), 'utf8'),
])));
const upgrade = '20261115010000_unify_meeting_tasks.sql';
const canonical = '20261114080000_create_tasks.sql';

async function database() {
  const db = new PGlite();
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    grant usage on schema public to anon, authenticated, service_role;
    create schema auth;
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
    $$;
    create table auth.users(id uuid primary key, email text, encrypted_password text,
      email_confirmed_at timestamptz, raw_user_meta_data jsonb default '{}');
  `);
  return db;
}

test('migration versions are unique and the complete fresh chain applies', async () => {
  const versions = names.map(name => name.split('_')[0]);
  assert.equal(new Set(versions).size, versions.length);
  const db = await database();
  try {
    for (const name of names) await db.exec(sql[name]);
    assert.equal((await db.query(`select data_type from information_schema.columns
      where table_schema='public' and table_name='tasks' and column_name='id'`)).rows[0].data_type, 'uuid');
    // Run the real canonical ingestion payload, then query/update as the timeline does.
    await db.exec(`set role service_role`);
    const meeting = (await db.query(`insert into meetings(held_at,title,recording_id,summary)
      values ('2026-11-13T18:00:00-05:00','Synthetic meeting','test-audio','A summary') returning id`)).rows[0].id;
    const { rows: [task] } = await db.query(`insert into tasks(title,month_code,source,
      source_meeting_id,assignee_text,seat_text,deadline_text,due_date,deadline_at)
      values ('Book room','2026-11','meeting',$1,'Demo One','Secretary','Monday noon',
        '2026-11-16','2026-11-16T12:00:00-05:00') returning *`, [meeting]);
    assert.match(task.id, /^[a-f0-9-]{36}$/);
    assert.equal(task.status, 'todo');
    assert.match(task.task_code, /^WIN-202611-/);
    await db.query(`update tasks set status='in_progress' where id=$1`, [task.id]);
    assert.equal((await db.query(`select status from tasks where id=$1`, [task.id])).rows[0].status, 'in_progress');
    await db.exec('reset role; set role anon');
    await assert.rejects(db.query('select * from meetings'));
    await assert.rejects(db.query('select * from task_dependencies'));
  } finally { await db.close(); }
});

test('direct browser RPCs require consent and actual password setup, even for a president', async () => {
  const db = await database();
  const id = '33333333-3333-4333-8333-333333333333';
  try {
    for (const name of names) await db.exec(sql[name]);
    await db.query(`insert into members(code,display_name,email,contact_consent,board_role)
      values('ALICE','Alice','alice@example.com',true,'President')`);
    await db.query('insert into auth.users(id,email,email_confirmed_at) values($1,$2,now())', [id, 'alice@example.com']);
    await db.query("select set_config('request.jwt.claim.sub',$1,false)", [id]);
    await db.exec('set role authenticated');
    assert.equal((await db.query('select public.current_board_member_code() as code')).rows[0].code, null);
    assert.equal((await db.query('select public.can_review_task_requests() as allowed')).rows[0].allowed, false);
    await assert.rejects(db.query("select public.submit_task_reassignment($1,'OTHER','test')", [id]), /completed password setup/);
    await db.exec('reset role');
    await db.query("update auth.users set encrypted_password='synthetic-password-hash' where id=$1", [id]);
    await db.exec('set role authenticated');
    assert.equal((await db.query('select public.current_board_member_code() as code')).rows[0].code, 'ALICE');
    assert.equal((await db.query('select public.can_review_task_requests() as allowed')).rows[0].allowed, true);
    await db.exec('reset role');
    await db.query("update members set email=null,contact_consent=false where code='ALICE'");
    await db.exec('set role authenticated');
    assert.equal((await db.query('select public.current_board_member_code() as code')).rows[0].code, null);
    assert.equal((await db.query('select public.can_review_task_requests() as allowed')).rows[0].allowed, false);
  } finally { await db.close(); }
});

test('numeric legacy tasks and dependency links survive conversion and reapplication', async () => {
  const db = await database();
  try {
    await db.exec(sql['0001_init.sql']);
    await db.exec(`
      insert into seats(name) values ('Secretary');
      insert into people(name) values ('Demo One');
      insert into meetings(held_at,title,recording_id) values ('2026-11-13T23:00Z','Legacy','legacy-audio');
      insert into tasks(title,status,seat_id,assignee_id,source_meeting_id,deadline_raw,deadline_at)
        values ('First','open',1,1,1,'Monday noon','2026-11-16T17:00Z'),
               ('Second','blocked',1,1,1,null,null);
      insert into task_dependencies values (2,1);
    `);
    for (const name of names.filter(name => name !== '0001_init.sql')) await db.exec(sql[name]);
    const tasks = (await db.query('select * from tasks order by legacy_task_id')).rows;
    assert.equal(tasks.length, 2);
    assert.equal(tasks[0].status, 'todo');
    assert.equal(tasks[0].assignee_text, 'Demo One');
    assert.equal(tasks[0].seat_text, 'Secretary');
    assert.equal(tasks[0].deadline_text, 'Monday noon');
    assert.equal(tasks[0].semester_code, 'fall-2026');
    assert.equal(tasks[0].source_meeting_id, 1);
    assert.deepEqual((await db.query('select * from task_dependencies')).rows,
      [{ task_id: tasks[1].id, depends_on_id: tasks[0].id }]);
    assert.equal((await db.query('select count(*)::int n from winnie_legacy.tasks')).rows[0].n, 2);
    await db.exec(sql[upgrade]);
    assert.deepEqual((await db.query('select id,task_code from tasks order by legacy_task_id')).rows,
      tasks.map(({ id, task_code }) => ({ id, task_code })));
  } finally { await db.close(); }
});

test('existing UUID tasks retain IDs, codes and ownership without the legacy bootstrap', async () => {
  const db = await database();
  try {
    for (const name of names.filter(name => name >= canonical && name < '20261115000001')) {
      await db.exec(sql[name]);
    }
    await db.exec("insert into public.members(code,display_name) values('DEMO','Demo')");
    const { rows: [before] } = await db.query(`insert into tasks(title,month_code,owner_code,
      assignee_text,status) values ('Existing tracker task','2026-11','DEMO','Demo','in_progress') returning *`);
    await db.exec(sql['0001_init.sql']); // Historical bootstrap is safe on an existing UUID store.
    await db.exec(sql[upgrade]); // Works even if the old summary migration was never applied.
    const { rows: [after] } = await db.query('select * from tasks where id=$1', [before.id]);
    for (const key of Object.keys(before)) assert.deepEqual(after[key], before[key], key);
    await db.exec(sql['20261115000001_meeting_summary.sql']);
  } finally { await db.close(); }
});
