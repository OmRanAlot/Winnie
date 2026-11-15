import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {test} from 'node:test';
import {PGlite} from '@electric-sql/pglite';
const folder=new URL('../migrations/',import.meta.url);
const migrations=await Promise.all((await readdir(folder)).filter(n=>n.endsWith('.sql')).sort().map(n=>readFile(new URL(n,folder),'utf8')));
test('private inbox dedupes deliveries, fences concurrent jobs and never retries an uncertain send',async()=>{
 const db=new PGlite();
 try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;create schema auth;
   grant usage on schema public,auth to anon,authenticated,service_role;
   create function auth.uid() returns uuid language sql as $$select null::uuid$$;
   create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,encrypted_password text,raw_user_meta_data jsonb default '{}');`);
  for(const sql of migrations) await db.exec(sql);
  await db.exec('set role service_role');
  const hook='11111111-1111-4111-8111-111111111111',token='22222222-2222-4222-8222-222222222222',other='33333333-3333-4333-8333-333333333333';
  const put=()=>db.query("select photon_inbox_put($1,'event','digest','{\"text\":\"Synthetic private message\"}'::jsonb) id",[hook]);
  const id=(await put()).rows[0].id;
  assert.equal((await put()).rows[0].id,id);
  await assert.rejects(db.query("select photon_inbox_put($1,'event','tampered','{}')",[hook]),/content changed/);
  const claim=async t=>(await db.query('select photon_inbox_claim($1,$2) r',[id,t])).rows[0].r;
  assert.equal((await claim(token)).payload.text,'Synthetic private message');
  assert.equal((await claim(other)).busy,true);
  assert.equal((await db.query("select photon_inbox_advance($1,$2,'ready','Saved reply') r",[id,token])).rows[0].r,true);
  assert.equal((await claim(other)).busy,true,'cached reply must still be leased to original worker');
  assert.equal((await db.query("select photon_inbox_advance($1,$2,'sending') r",[id,other])).rows[0].r,false);
  await db.query("select photon_inbox_advance($1,$2,'sending')",[id,token]);
  await db.query("update photon_inbox set claimed_at=now()-interval '3 minutes' where id=$1",[id]);
  assert.equal((await claim(other)).done,true);
  assert.equal((await db.query('select state from photon_inbox where id=$1',[id])).rows[0].state,'uncertain');
  await db.exec('reset role;set role authenticated');
  await assert.rejects(db.query('select * from photon_inbox'),/permission denied/);
  await assert.rejects(db.query('select photon_inbox_claim($1,$2)',[id,token]),/permission denied/);
 }finally{await db.close();}
});
