// Exercise the real attendance schema, atomic writes, import retries and role permissions.
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

test('attendance persists a roster set atomically and repeated imports preserve edits', async () => {
  const db = new PGlite();
  try {
    await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
      grant usage on schema public to anon, authenticated, service_role;
      create schema auth;
      create function auth.uid() returns uuid language sql stable as $$
        select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
      create table auth.users(id uuid primary key,email text,encrypted_password text,email_confirmed_at timestamptz,
        raw_user_meta_data jsonb default '{}');`);
    const dir = new URL('../migrations/', import.meta.url);
    for (const name of (await readdir(dir)).filter(n => n.endsWith('.sql')).sort()) {
      await db.exec(await readFile(new URL(name, dir), 'utf8'));
    }
    await db.exec(`insert into members(code,display_name) values ('A','Alice'),('B','Bob');
      set role service_role;`);
    const records = [{ held_at: '2026-09-03T12:00:00-04:00', title: 'Board',
      recording_id: 'attendance-csv:2026-09-03', attendees: ['A', 'B'] }];
    const importRows = rows => db.query('select import_meeting_attendance($1::jsonb) n', [JSON.stringify(rows)]);
    assert.equal((await importRows(records)).rows[0].n, 1);
    const id = (await db.query('select id from meetings')).rows[0].id;
    const attendees = async () => (await db.query('select member_code from meeting_attendance order by member_code')).rows.map(r => r.member_code);
    assert.deepEqual(await attendees(), ['A', 'B']);
    await assert.rejects(db.query('select save_meeting_attendance($1,$2::text[])', [id, ['UNKNOWN']]));
    assert.deepEqual(await attendees(), ['A', 'B']);
    await db.query('select save_meeting_attendance($1,$2::text[])', [id, ['B', 'B']]);
    assert.deepEqual(await attendees(), ['B']);
    assert.equal((await importRows(records)).rows[0].n, 0);
    assert.deepEqual(await attendees(), ['B']);
    await db.query('select save_meeting_attendance($1,$2::text[])', [id, []]);
    assert.deepEqual(await attendees(), []);
    assert.ok((await db.query('select attendance_recorded_at from meetings')).rows[0].attendance_recorded_at);
    await assert.rejects(importRows([
      { ...records[0], recording_id: 'new-valid' },
      { ...records[0], recording_id: 'new-invalid', attendees: ['UNKNOWN'] },
    ]));
    assert.equal((await db.query('select count(*)::int n from meetings')).rows[0].n, 1);
    await assert.rejects(db.query('select save_meeting_attendance(999,ARRAY[]::text[])'));
    for (const role of ['anon', 'authenticated']) {
      await db.exec(`reset role; set role ${role}`);
      await assert.rejects(db.query('select * from meeting_attendance'));
      await assert.rejects(db.query('select save_meeting_attendance($1,$2::text[])', [id, ['A']]));
      await assert.rejects(importRows(records));
    }
  } finally { await db.close(); }
});
