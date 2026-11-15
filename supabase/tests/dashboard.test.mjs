// Apply the real ordered schema and exercise durable writes and grants with synthetic data.
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';
const directory = new URL('../migrations/',import.meta.url);
const migrations = await Promise.all((await readdir(directory)).filter(n=>n.endsWith('.sql')).sort()
  .map(n=>readFile(new URL(n,directory),'utf8')));
const id='11111111-1111-4111-8111-111111111111';
async function database() {
  const db=new PGlite();
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; grant usage on schema public,auth to anon,authenticated,service_role;
    create function auth.uid() returns uuid language sql as $$ select null::uuid $$;
    create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,
      encrypted_password text,raw_user_meta_data jsonb default '{}');`);
  for(const sql of migrations) await db.exec(sql);
  return db;
}

test('completion timestamps track transitions; independent notes and schedules persist',async()=>{
  const db=await database();
  try {
    const {rows:[task]}=await db.query(`insert into tasks(title,month_code,start_date,due_date,due_time,notes)
      values('Synthetic task','2026-11','2026-11-15','2026-11-20','18:30','Original note') returning *`);
    assert.equal(task.completed_at,null);
    await db.query("update tasks set status='done' where id=$1",[task.id]);
    const done=(await db.query('select * from tasks where id=$1',[task.id])).rows[0];
    assert.ok(done.completed_at); assert.equal(done.due_time,'18:30:00');
    await db.query("update tasks set notes='Updated note' where id=$1",[task.id]);
    assert.equal((await db.query('select completed_at from tasks where id=$1',[task.id])).rows[0].completed_at.getTime(),done.completed_at.getTime());
    await assert.rejects(db.query("update tasks set start_date='2026-12-01' where id=$1",[task.id]),/tasks_start_before_due/);
    await db.query("update tasks set status='in_progress' where id=$1",[task.id]);
    assert.equal((await db.query('select completed_at from tasks where id=$1',[task.id])).rows[0].completed_at,null);
  } finally {await db.close();}
});

test('member edits sync linked profiles atomically without granting privileges; private forms remain server-only',async()=>{
  const db=await database();
  try {
    await db.exec("insert into members(code,display_name,board_role) values('A','Alice','Treasurer')");
    await db.query('insert into auth.users(id,email) values($1,$2)',[id,'alice@example.com']);
    await db.query("update profiles set member_code='A' where id=$1",[id]);
    await db.exec('set role service_role');
    await db.query('select public.update_dashboard_member($1,$2::jsonb)',['A',JSON.stringify({
      display_name:'Alice Updated',board_role:'Secretary',skills:['Python'],previous_roles:[],previous_role_skills_manual:['Planning'],
    })]);
    const p=(await db.query('select name,role,skills,is_admin from profiles where id=$1',[id])).rows[0];
    assert.deepEqual(p,{name:'Alice Updated',role:'Secretary',skills:['Python'],is_admin:false});
    assert.equal((await db.query("select previous_roles_override from members where code='A'")).rows[0].previous_roles_override,true);
    await assert.rejects(db.query('select public.update_dashboard_member($1,$2::jsonb)',['A','{"is_admin":true}']),/Unsupported/);
    await db.query("insert into member_evaluations(member_code,comments,reviewer_id) values('A','Feedback',$1)",[id]);
    await db.query('insert into dashboard_task_drafts(profile_id,form) values($1,$2::jsonb)',[id,'{"title":"Stored draft"}']);
    assert.equal((await db.query('select form from dashboard_task_drafts')).rows[0].form.title,'Stored draft');
    await db.exec('reset role; set role authenticated');
    await assert.rejects(db.exec('select * from member_evaluations'),/permission denied/);
    await assert.rejects(db.exec('select * from dashboard_task_drafts'),/permission denied/);
    await assert.rejects(db.query('select update_dashboard_member($1,$2::jsonb)',['A','{}']),/permission denied/);
  } finally {await db.close();}
});
