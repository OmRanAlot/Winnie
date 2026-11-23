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
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
    $$;
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

test('roster onboarding and offboarding change access and retain task and alias history', async () => {
  const db = await database();
  const bob = '22222222-2222-4222-8222-222222222222';
  const replacement = '33333333-3333-4333-8333-333333333333';
  const save = async (code, fields, create = false, actor = id) => (await db.query(
    "select public.save_board_member($1,$2,'fall-2026',$3::jsonb,$4) as member",
    [actor, code, JSON.stringify(fields), create],
  )).rows[0].member;
  const addAuthUser = (uuid, email) => db.query(
    "insert into auth.users(id,email,email_confirmed_at,encrypted_password) values($1,$2,now(),'hash')",
    [uuid, email],
  );
  const profile = async uuid => (await db.query(
    'select member_code,role,phone_number,is_admin from profiles where id=$1', [uuid],
  )).rows[0];
  try {
    await db.exec(`insert into public.members(code,display_name,email,contact_consent)
      values('ADMIN','Board Admin','admin@example.com',true)`);
    await addAuthUser(id, 'admin@example.com');
    await db.query('update profiles set is_admin=true where id=$1', [id]);
    await addAuthUser(bob, 'bob@example.com');

    await db.exec('set role service_role');
    const created = await save('BOB', {
      display_name: 'Bob Example', board_role: 'Treasurer', email: 'BOB@example.com',
      phone_number: '(202) 555-0123', contact_consent: true,
    }, true);
    assert.equal(created.active, true);
    assert.equal(created.email, 'bob@example.com');
    assert.deepEqual(await profile(bob), {
      member_code: 'BOB', role: 'Treasurer', phone_number: '(202) 555-0123', is_admin: false,
    });
    await assert.rejects(save('NEW', {display_name:'New Member', email:'new@example.com'}, true),
      /permission to store/);
    await assert.rejects(save('NEW', {display_name:'New Member'}, true, bob), /Administrator access/);
    await assert.rejects(save('NEW', {display_name:'Bob Example'}, true), /already on the board roster/);
    assert.equal((await db.query("select count(*)::integer as n from members where code='NEW'")).rows[0].n, 0);
    await assert.rejects(save('ADMIN', {active:false}), /another administrator/);
    await assert.rejects(save('ADMIN', {email:'other@example.com'}), /another administrator/);
    await assert.rejects(save('BOB', {is_admin:true}), /Unsupported roster field/);

    await db.exec(`insert into public.member_identities(platform,sender_id,member_code,reminders_enabled)
      values('imessage','+12025550123','BOB',true)`);
    await db.exec(`insert into public.tasks(title,month_code,owner_code)
      values('Historical task','2026-11','BOB')`);
    await save('BOB', {display_name:'Robert Example', board_role:'', phone_number:'+1 202-555-0123'});
    assert.deepEqual(await profile(bob), {
      member_code: 'BOB', role: 'member', phone_number: '+1 202-555-0123', is_admin: false,
    });
    const identities = () => db.query("select sender_id from member_identities where member_code='BOB'");
    assert.deepEqual((await identities()).rows, [{sender_id:'+12025550123'}]);
    await save('BOB', {phone_number:'+12025550199'});
    assert.deepEqual((await identities()).rows, []);
    assert.deepEqual((await db.query("select alias from member_aliases where member_code='BOB' order by alias")).rows,
      [{alias:'Bob Example'}, {alias:'Robert Example'}]);

    await save('BOB', {active:false});
    assert.equal((await profile(bob)).member_code, 'BOB');
    assert.equal((await db.query("select owner_code from tasks where title='Historical task'")).rows[0].owner_code, 'BOB');
    await db.exec('reset role');
    await db.query("select set_config('request.jwt.claim.sub',$1,false)", [bob]);
    await db.exec('set role authenticated');
    assert.equal((await db.query('select current_board_member_code() as code')).rows[0].code, null);
    await assert.rejects(save('BOB', {active:true}), /permission denied/);
    await db.exec('reset role; set role service_role');
    await save('BOB', {active:true, board_role:'Secretary'});
    assert.equal((await db.query('select current_board_member_code() as code')).rows[0].code, 'BOB');
    assert.equal((await profile(bob)).role, 'Secretary');

    await db.exec('reset role');
    await db.query('update profiles set is_admin=true where id=$1', [bob]);
    await addAuthUser(replacement, 'updated@example.com');
    await db.exec('set role service_role');
    await save('BOB', {email:'updated@example.com'});
    assert.deepEqual(await profile(bob), {member_code:null, role:'Secretary', phone_number:null, is_admin:false});
    assert.deepEqual(await profile(replacement), {
      member_code:'BOB', role:'Secretary', phone_number:'+12025550199', is_admin:false,
    });
    assert.equal((await db.query('select current_board_member_code() as code')).rows[0].code, null);
  } finally { await db.close(); }
});
