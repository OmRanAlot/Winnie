// Execute the complete schema and verify memory is private, versioned and resettable.
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {test} from 'node:test';
import {PGlite} from '@electric-sql/pglite';
const folder=new URL('../migrations/',import.meta.url);
const migrations=await Promise.all((await readdir(folder)).filter(n=>n.endsWith('.sql')).sort().map(n=>readFile(new URL(n,folder),'utf8')));
async function database(){
 const db=new PGlite();
 await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
 create schema auth; grant usage on schema public,auth to anon,authenticated,service_role;
 create function auth.uid() returns uuid language sql as $$ select null::uuid $$;
 create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,encrypted_password text,raw_user_meta_data jsonb default '{}');`);
 for(const sql of migrations) await db.exec(sql);
 await db.exec("insert into members(code,display_name,board_role,email,contact_consent) values('A','Synthetic A','Member','a@example.com',true),('B','Synthetic B','Member','b@example.com',true)");
 return db;
}
const thread='a'.repeat(64);
test('memory checkpoints remain service-only; members and conversations have distinct keys',async()=>{
 const db=await database();
 try{
  await db.exec('set role service_role');
  const save=(member,key,version,state,ttl=7200)=>db.query('select save_photon_memory($1,$2,$3,$4::jsonb,$5) memory',[member,key,version,JSON.stringify(state),ttl]);
  assert.equal((await db.query('select load_photon_memory($1,$2) memory',['A',thread])).rows[0].memory,null);
  const row=(await save('A',thread,0,{checkpoint:{channel_values:{turns:[{user:'Synthetic question',assistant:'Synthetic answer'}]}}})).rows[0].memory;
  assert.equal(row.version,1);
  assert.equal((await db.query('select load_photon_memory($1,$2) memory',['B',thread])).rows[0].memory,null);
  assert.equal((await db.query('select load_photon_memory($1,$2) memory',['A','b'.repeat(64)])).rows[0].memory,null);
  await db.exec('reset role; set role authenticated');
  await assert.rejects(db.query('select * from photon_conversation_memory'),/permission denied/);
  await assert.rejects(save('A',thread,1,{}),/permission denied/);
  await assert.rejects(db.query('select load_photon_memory($1,$2)',['A',thread]),/permission denied/);
  await db.exec('reset role; set role anon');
  await assert.rejects(db.query('select * from photon_conversation_memory'),/permission denied/);
 }finally{await db.close();}
});
test('stale writers cannot restore forgotten history; consent, payload size and TTL are enforced',async()=>{
 const db=await database();
 try{
  await db.exec('set role service_role');
  const save=(version,state,ttl=7200)=>db.query('select save_photon_memory($1,$2,$3,$4::jsonb,$5) memory',['A',thread,version,JSON.stringify(state),ttl]);
  await save(0,{checkpoint:{channel_values:{turns:[]}}});
  const cleared=(await save(1,{})).rows[0].memory;
  assert.equal(cleared.version,2); assert.deepEqual(cleared.state,{});
  await assert.rejects(save(1,{checkpoint:{old:true}}),/Conversation changed/);
  await assert.rejects(save(2,{},1),/Invalid memory checkpoint/);
  await assert.rejects(save(2,{text:'x'.repeat(140000)}),/Invalid memory checkpoint/);
  await db.exec('reset role');
  await db.exec("update members set contact_consent=false,email=null where code='A'");
  await db.exec('set role service_role');
  await assert.rejects(save(2,{}),/Active consenting/);
  await assert.rejects(db.query('select load_photon_memory($1,$2)',['A',thread]),/Active consenting/);
 }finally{await db.close();}
});
