// Executes the real profile migration in PostgreSQL (PGlite), without hosted credentials.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

const alice = '11111111-1111-4111-8111-111111111111';
const bob = '22222222-2222-4222-8222-222222222222';
const migration = await readFile(
  new URL('../migrations/20261114120001_create_profiles.sql', import.meta.url), 'utf8',
);

async function createDatabase() {
  const db = new PGlite();
  // Stand-ins for Supabase's managed schema/roles; the profiles migration is unmodified.
  await db.exec(`
    create role anon;
    create role authenticated;
    create role service_role bypassrls;
    create schema auth;
    grant usage on schema public, auth to anon, authenticated, service_role;
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
    $$;
    create table auth.users (
      id uuid primary key,
      email text,
      raw_user_meta_data jsonb default '{}'
    );
    insert into auth.users (id, email, raw_user_meta_data) values
      ('${alice}', 'alice@example.com', '{"name":"Alice"}');
  `);
  await db.exec(migration);
  return db;
}

async function asMember(db, id, operation) {
  await db.query("select set_config('request.jwt.claim.sub', $1, false)", [id]);
  await db.exec('set role authenticated');
  try {
    return await operation();
  } finally {
    await db.exec('reset role');
  }
}

test('backfills Auth users and ignores user-supplied privileges on signup', async () => {
  const db = await createDatabase();
  try {
    assert.deepEqual((await db.query('select name, email, role, is_admin, skills from public.profiles')).rows,
      [{ name: 'Alice', email: 'alice@example.com', role: 'member', is_admin: false, skills: [] }]);
    await db.query('insert into auth.users (id, email, raw_user_meta_data) values ($1, $2, $3)',
      [bob, 'bob@example.com', { name: 'Bob', role: 'president', is_admin: true }]);
    const { rows } = await db.query('select name, role, is_admin from public.profiles where id = $1', [bob]);
    assert.deepEqual(rows, [{ name: 'Bob', role: 'member', is_admin: false }]);
    const columns = await db.query("select column_name from information_schema.columns where table_name = 'profiles'");
    assert.ok(!columns.rows.some(row => /password/i.test(row.column_name)));
  } finally {
    await db.close();
  }
});

test('members can read/edit only their own safe fields; admin access is server-only', async () => {
  const db = await createDatabase();
  try {
    await db.query('insert into auth.users (id, email) values ($1, $2)', [bob, 'bob@example.com']);
    await asMember(db, alice, async () => {
      assert.deepEqual((await db.query('select id from public.profiles')).rows, [{ id: alice }]);
      await db.query('update public.profiles set name=$1, phone_number=$2, skills=$3 where id=$4',
        ['Alice Updated', '+12025550123', ['Python', 'Event planning'], alice]);
      assert.equal((await db.query('update public.profiles set name=$1 where id=$2 returning id',
        ['Not allowed', bob])).rows.length, 0);
      for (const assignment of ["is_admin=true", "role='president'", "email='other@example.com'", `id='${bob}'`]) {
        await assert.rejects(db.exec(`update public.profiles set ${assignment} where id='${alice}'`),
          /permission denied/i);
      }
      await assert.rejects(db.exec('delete from public.profiles'), /permission denied/i);
      await assert.rejects(db.query('insert into public.profiles (id) values ($1)', [bob]), /permission denied/i);
      await assert.rejects(db.query('update public.profiles set skills=$1 where id=$2', [[''], alice]),
        /Each skill/);
      await assert.rejects(db.query('update public.profiles set skills=$1 where id=$2', [[null], alice]),
        /check constraint/);
      await assert.rejects(db.exec('select public.sync_auth_profile()'), /permission denied/i);
    });
    await db.exec('set role anon');
    await assert.rejects(db.exec('select * from public.profiles'), /permission denied/i);
    await db.exec('reset role; set role service_role');
    await db.query("update public.profiles set role='president', is_admin=true where id=$1", [alice]);
    assert.equal((await db.query('select id from public.profiles')).rows.length, 2);
    await assert.rejects(db.query('update public.profiles set skills=$1 where id=$2', [[' '], alice]),
      /Each skill/);
    await db.exec('reset role');
    const row = (await db.query('select name, skills, is_admin from public.profiles where id=$1', [alice])).rows[0];
    assert.equal(row.name, 'Alice Updated');
    assert.deepEqual(row.skills, ['Python', 'Event planning']);
    assert.equal(row.is_admin, true);
  } finally {
    await db.close();
  }
});

test('Auth email updates sync without overwriting profile edits; deleting Auth user cascades', async () => {
  const db = await createDatabase();
  try {
    await db.query('update public.profiles set name=$1, phone_number=$2, skills=$3 where id=$4',
      ['Custom name', '+12025550123', ['Python'], alice]);
    await db.query('update auth.users set email=$1 where id=$2', ['new@example.com', alice]);
    const row = (await db.query('select name, email, phone_number, skills from public.profiles where id=$1', [alice])).rows[0];
    assert.deepEqual(row, { name: 'Custom name', email: 'new@example.com', phone_number: '+12025550123', skills: ['Python'] });
    await db.query('delete from auth.users where id=$1', [alice]);
    assert.deepEqual((await db.query('select * from public.profiles')).rows, []);
  } finally {
    await db.close();
  }
});
