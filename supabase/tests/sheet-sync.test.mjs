// Real PostgreSQL transactions: source identity, concurrency guards, baseline updates and RLS.
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

test('Google tracker apply is atomic, revision checked and server only', async () => {
  const db = new PGlite();
  try {
    await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
      grant usage on schema public to anon,authenticated,service_role; create schema auth;
      create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
      create table auth.users(id uuid primary key,email text,encrypted_password text,
        email_confirmed_at timestamptz,raw_user_meta_data jsonb default '{}');`);
    const dir = new URL('../migrations/', import.meta.url);
    for (const name of (await readdir(dir)).filter(n => n.endsWith('.sql')).sort()) {
      await db.exec(await readFile(new URL(name, dir), 'utf8'));
    }
    await db.exec('set role service_role');
    const values = {title:'Book room',description:'From sheet',month_code:'2026-10',
      semester_code:'fall-2026',source:'sheet',status:'todo',priority:'normal',assignee_text:'Alice',
      deadline_text:'10/20/2026',due_date:'2026-10-20',event_tag:'Workshop',category:null,
      project_name:null,snapshot_month:'2026-10',source_spreadsheet_id:'demo-sheet',
      source_task_id:'FALL26-001',source_tab_id:'7',source_tab_name:'October 2026'};
    const plan = {source_key:'fall-board',spreadsheet_id:'demo-sheet',semester_code:'fall-2026',
      snapshot_month:'2026-10',project_name:null,conflicts:[],
      operations:[{action:'insert',source_task_id:'FALL26-001',values,source_values:values,
        expected_state_version:null}],summary:{insert:1,update:0,unchanged:0}};
    const apply = p => db.query('select apply_sheet_sync($1::jsonb) result', [JSON.stringify(p)]);
    assert.deepEqual((await apply(plan)).rows[0].result, plan.summary);
    const task = (await db.query('select * from tasks')).rows[0];
    assert.match(task.task_code, /^WIN-/);
    assert.equal((await db.query('select version from sheet_sync_state')).rows[0].version, 1);
    await assert.rejects(apply(plan)); // Retrying the stale insertion cannot duplicate it.
    const revision = task.updated_at.toISOString();
    const update = structuredClone(plan);
    update.operations = [{action:'update',source_task_id:'FALL26-001',id:task.id,
      expected_updated_at:revision,expected_state_version:1,
      values:{status:'done',owner_code:'UNTRUSTED',source_task_id:'WRONG'},source_values:{...values,status:'done'}}];
    update.summary = {insert:0,update:1,unchanged:0};
    await apply(update);
    let saved = (await db.query('select * from tasks')).rows[0];
    assert.equal(saved.status, 'done');
    assert.equal(saved.owner_code, null);
    assert.equal(saved.source_task_id, 'FALL26-001');
    const before = (await db.query('select version from sheet_sync_state')).rows[0].version;
    const failed = structuredClone(plan);
    failed.operations = [
      {...plan.operations[0],source_task_id:'FALL26-002',values:{...values,source_task_id:'FALL26-002'}},
      {...update.operations[0],expected_updated_at:'2000-01-01T00:00:00Z'},
    ];
    await assert.rejects(apply(failed));
    assert.equal((await db.query('select count(*)::int n from tasks')).rows[0].n, 1);
    assert.equal((await db.query('select version from sheet_sync_state')).rows[0].version, before);
    assert.equal((await db.query('select count(*)::int n from sheet_sync_runs')).rows[0].n, 2);
    // Even unchanged rows are revision checked, so baseline cannot advance across a local edit.
    saved = (await db.query('select * from tasks')).rows[0];
    const unchanged = structuredClone(update);
    unchanged.operations[0] = {...update.operations[0],action:'unchanged',values:{},
      expected_state_version:2,expected_updated_at:saved.updated_at.toISOString()};
    await apply(unchanged);
    assert.equal((await db.query('select version from sheet_sync_state')).rows[0].version, 3);
    await assert.rejects(apply(unchanged));
    await assert.rejects(apply({...plan,conflicts:[{field:'status'}]}));
    // Older snapshot cannot add new tasks after a newer month was imported.
    await db.query("update tasks set snapshot_month='2026-11'");
    await assert.rejects(apply({...plan,operations:[{...plan.operations[0],source_task_id:'NEW',
      values:{...values,source_task_id:'NEW'}}]}));
    for (const role of ['anon','authenticated']) {
      await db.exec(`reset role; set role ${role}`);
      await assert.rejects(db.query('select * from sheet_sync_state'));
      await assert.rejects(db.query('select * from sheet_sync_runs'));
      await assert.rejects(apply(plan));
    }
  } finally { await db.close(); }
});
