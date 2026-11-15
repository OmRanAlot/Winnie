import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createClient } from '@supabase/supabase-js';
import { createSessionFetch } from '../src/lib/sessionFetch.js';

const url = 'https://test.supabase.co';
const jwt = (sub, revision = 0) => `e30.${Buffer.from(JSON.stringify({ sub, revision, exp: 4102444800 })).toString('base64url')}.signature`;
const old = jwt('user');
const fresh = jwt('user', 1);
const expired = () => Response.json({ code: 'PGRST301', message: 'JWT expired' }, { status: 401 });
function setup(handler = () => Response.json({ ok: true })) {
  let session = { access_token: old, user: { id: 'user' } };
  let refreshes = 0;
  const calls = [];
  const auth = {
    getSession: async () => ({ data: { session }, error: null }),
    refreshSession: async () => {
      refreshes++;
      await new Promise(resolve => setTimeout(resolve, 5));
      session = { ...session, access_token: fresh };
      return { data: { session }, error: null };
    },
  };
  const fetcher = createSessionFetch(url, () => auth, async (input, init) => {
    const request = new Request(input, init);
    calls.push({ url: request.url, headers: request.headers, method: request.method, body: await request.text() });
    return request.headers.get('Authorization') === `Bearer ${old}` ? expired() : handler(request);
  });
  return { auth, calls, fetcher, setSession: value => { session = value; }, get refreshes() { return refreshes; } };
}
const options = () => ({ method: 'POST', headers: { Authorization: `Bearer ${old}`, apikey: 'public-key', 'Content-Type': 'application/json' }, body: JSON.stringify({ task: 'one' }) });

test('concurrent expired reads and RPCs refresh once and preserve request bodies and headers', async () => {
  const f = setup();
  const responses = await Promise.all(Array.from({ length: 3 }, () => f.fetcher(`${url}/rest/v1/rpc/submit`, options())));
  assert.ok(responses.every(r => r.ok));
  assert.equal(f.refreshes, 1);
  assert.equal(f.calls.length, 6);
  for (const call of f.calls.slice(3)) {
    assert.equal(call.headers.get('Authorization'), `Bearer ${fresh}`);
    assert.equal(call.headers.get('apikey'), 'public-key');
    assert.equal(call.body, JSON.stringify({ task: 'one' }));
    assert.equal(call.method, 'POST');
  }
});

test('a token already refreshed by the SDK is reused', async () => {
  const f = setup();
  f.setSession({ access_token: fresh, user: { id: 'user' } });
  assert.equal((await f.fetcher(`${url}/rest/v1/profiles`, options())).status, 200);
  assert.equal(f.refreshes, 0);
});

test('failed refresh, signed out, and changed accounts do not replay', async () => {
  for (const mode of ['failed', 'signed-out', 'changed']) {
    const f = setup();
    if (mode === 'failed') f.auth.refreshSession = async () => ({ data: { session: null }, error: new Error('revoked') });
    if (mode === 'signed-out') f.setSession(null);
    if (mode === 'changed') f.setSession({ access_token: jwt('other'), user: { id: 'other' } });
    const response = await f.fetcher(`${url}/rest/v1/profiles`, options());
    assert.equal(response.status, 401);
    assert.equal((await response.json()).message, 'JWT expired');
    assert.equal(f.calls.length, 1);
  }
});

test('a second expiry stops after one retry', async () => {
  const f = setup(expired);
  assert.equal((await f.fetcher(`${url}/rest/v1/profiles`, options())).status, 401);
  assert.equal(f.calls.length, 2);
  assert.equal(f.refreshes, 1);
});

test('auth and other origins bypass recovery', async () => {
  const f = setup();
  for (const endpoint of [`${url}/auth/v1/token`, 'https://other.example/rest/v1/profiles']) {
    assert.equal((await f.fetcher(endpoint, options())).status, 401);
  }
  assert.equal(f.refreshes, 0);
  assert.equal(f.calls.length, 2);
});

test('permission errors, other JWT errors, and server failures are not retried', async () => {
  for (const [status, code, message] of [[403, '42501', 'permission denied'], [401, 'PGRST301', 'invalid signature'], [401, 'PGRST303', 'JWT issued at future'], [500, 'XX000', 'failure']]) {
    let calls = 0;
    const fetcher = createSessionFetch(url, () => { throw new Error('must not refresh'); }, async () => {
      calls++;
      return Response.json({ code, message }, { status });
    });
    assert.equal((await fetcher(`${url}/rest/v1/profiles`, options())).status, status);
    assert.equal(calls, 1);
  }
});

test('real Supabase SDK refreshes and retries an expired PostgREST request', async () => {
  const session = { access_token: old, refresh_token: 'refresh-old', expires_at: 4102444800, expires_in: 3600, token_type: 'bearer', user: { id: 'user' } };
  const storage = new Map([['test-auth', JSON.stringify(session)]]);
  let refreshes = 0;
  let queries = 0;
  const fetcher = createSessionFetch(url, () => client.auth, async (input, init) => {
    const request = new Request(input, init);
    if (request.url.includes('/auth/v1/token')) {
      refreshes++;
      return Response.json({ ...session, access_token: fresh, refresh_token: 'refresh-new' });
    }
    queries++;
    return request.headers.get('Authorization') === `Bearer ${old}` ? expired() : Response.json([{ id: 'user' }]);
  });
  const client = createClient(url, 'sb_publishable_test', {
    auth: { autoRefreshToken: false, detectSessionInUrl: false, storageKey: 'test-auth', storage: {
      getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key),
    } }, global: { fetch: fetcher },
  });
  const result = await client.from('profiles').select('id');
  assert.equal(result.error, null);
  assert.deepEqual(result.data, [{ id: 'user' }]);
  assert.equal(refreshes, 1);
  assert.equal(queries, 2);
  assert.equal((await client.auth.getSession()).data.session.access_token, fresh);
});
