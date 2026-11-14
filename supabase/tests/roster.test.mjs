// Exercise the real roster/profile migrations in PostgreSQL with synthetic users only.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

const alice = '11111111-1111-4111-8111-111111111111';
const bob = '22222222-2222-4222-8222-222222222222';
const migrations = await Promise.all([
  '20261114120000_add_messaging_members.sql',
  '20261114120001_create_profiles.sql',
  '20261114140000_link_member_roster.sql',
].map(name => readFile(new URL(`../migrations/${name}`, import.meta.url), 'utf8')));

const record = {
  code: 'WICS_ALICE', display_name: 'Alice Example', email: 'alice@example.com',
  phone_number: '+12025550123', contact_consent: true, board_role: 'Treasurer',
  major: 'Data Science', graduation_date: 'May 2029', graduation_year: 2029,
  girlhacks_title: 'Finance Chair', role_description: 'Manage finances.',
  role_responsibilities: ['Draft budgets.'], delegation_context_verified: true,
};

async function database() {
  const db = new PGlite();
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth;
    grant usage on schema public, auth to anon, authenticated, service_role;
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
    $$;
    create table auth.users (
      id uuid primary key, email text, email_confirmed_at timestamptz,
      raw_user_meta_data jsonb default '{}'
    );
  `);
  for (const sql of migrations) await db.exec(sql);
  return db;
}

async function importRows(db, records) {
  await db.query('select public.import_member_roster($1::jsonb)', [JSON.stringify(records)]);
}

test('roster-first invitation links only after Auth confirms exact email', async () => {
  const db = await database();
  try {
    await importRows(db, [record, {
      ...record, code: 'WICS_BOB', display_name: 'Bob Example', email: null,
      phone_number: null, contact_consent: false,
    }]);
    await db.query('insert into auth.users (id,email,raw_user_meta_data) values ($1,$2,$3)',
      [alice, 'alice@example.com', { name: 'Not authoritative', is_admin: true }]);
    let profile = (await db.query('select * from public.profiles where id=$1', [alice])).rows[0];
    assert.equal(profile.member_code, null);
    await db.query('update auth.users set email_confirmed_at=now() where id=$1', [alice]);
    profile = (await db.query('select * from public.profiles where id=$1', [alice])).rows[0];
    assert.equal(profile.member_code, 'WICS_ALICE');
    assert.equal(profile.role, 'Treasurer');
    assert.equal(profile.name, 'Alice Example');
    assert.equal(profile.graduation_year, 2029);
    assert.equal(profile.is_admin, false);
    await db.query('insert into auth.users (id,email,email_confirmed_at,raw_user_meta_data) values ($1,$2,now(),$3)',
      [bob, 'someone@example.com', { name: 'Bob Example', member_code: 'WICS_BOB' }]);
    assert.equal((await db.query('select member_code from public.profiles where id=$1', [bob])).rows[0].member_code, null);
    await assert.rejects(db.query('update auth.users set email=$1 where id=$2', ['other@example.com', alice]),
      /Contact an administrator/);
    assert.equal((await db.query('select count(*)::integer as n from auth.users')).rows[0].n, 2);
    assert.equal((await db.query('select count(*)::integer as n from public.member_identities')).rows[0].n, 0);
  } finally { await db.close(); }
});

test('existing confirmed profiles link on import; repeated imports preserve member codes and skills', async () => {
  const db = await database();
  try {
    await db.query('insert into auth.users (id,email,email_confirmed_at) values ($1,$2,now())', [alice, 'alice@example.com']);
    await db.exec("insert into public.members(code,display_name) values ('EXISTING','Alice Example')");
    await importRows(db, [record]);
    await db.query('update public.profiles set skills=$1 where id=$2', [['Python'], alice]);
    await importRows(db, [record]);
    assert.deepEqual((await db.query('select code from public.members')).rows, [{ code: 'EXISTING' }]);
    const profile = (await db.query('select member_code,skills from public.profiles where id=$1', [alice])).rows[0];
    assert.equal(profile.member_code, 'EXISTING');
    assert.deepEqual(profile.skills, ['Python']);
    await db.exec('set role authenticated');
    await assert.rejects(importRows(db, [record]), /permission denied/);
    await assert.rejects(db.exec('select email from public.members'), /permission denied/);
    await assert.rejects(db.exec("update public.profiles set member_code='EXISTING'"), /permission denied/);
    await db.exec('reset role');
  } finally { await db.close(); }
});

test('invalid contact consent rolls back the whole roster import', async () => {
  const db = await database();
  try {
    await assert.rejects(importRows(db, [record, {
      ...record, code: 'BAD', display_name: 'Bad Example', email: 'bad@example.com', contact_consent: false,
    }]), /members_contact_consent/);
    assert.equal((await db.query('select count(*)::integer as n from public.members')).rows[0].n, 0);
  } finally { await db.close(); }
});
