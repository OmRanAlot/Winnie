// Failures a live demo can hit must produce messages a person can act on.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assignRecordingTasks, request } from '../src/lib/api.js';

async function withFetch(fake, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try { await run(); } finally { globalThis.fetch = original; }
}

const htmlGateway = (status) => async () => ({ ok: false, status, json: async () => { throw new SyntaxError('not json'); } });

test('a gateway timeout says the work may still finish instead of showing a bare status code', async () => {
  await withFetch(htmlGateway(504), async () => {
    await assert.rejects(request('/planning/drafts', { method: 'POST' }), (error) => {
      assert.match(error.message, /took too long/i);
      assert.match(error.message, /may still finish/i);
      return true;
    });
  });
});

test('a 502/503 without a JSON body says the server is briefly unavailable', async () => {
  for (const status of [502, 503]) {
    await withFetch(htmlGateway(status), async () => {
      await assert.rejects(request('/tasks/records'), /temporarily unavailable/i);
    });
  }
});

test('a JSON error detail from the API is still shown as-is', async () => {
  await withFetch(async () => ({ ok: false, status: 503, json: async () => ({ detail: 'Planning took too long.' }) }), async () => {
    await assert.rejects(request('/planning/drafts', { method: 'POST' }), /Planning took too long\./);
  });
});

test('a client-side timeout is not reported as an unreachable server', async () => {
  const timeout = async () => { throw new DOMException('signal timed out', 'TimeoutError'); };
  await withFetch(timeout, async () => {
    await assert.rejects(request('/tasks/records'), (error) => {
      assert.match(error.message, /took too long/i);
      assert.doesNotMatch(error.message, /port 8000/);
      return true;
    });
  });
});

test('a network failure does not tell a hosted user to start a local server', async () => {
  await withFetch(async () => { throw new TypeError('Failed to fetch'); }, async () => {
    await assert.rejects(request('/tasks/records'), (error) => {
      assert.match(error.message, /Cannot reach the server/i);
      assert.doesNotMatch(error.message, /port 8000/);
      return true;
    });
  });
});

test('recording extraction reports when proposed tasks were not saved', async () => {
  const proposal = { title: 'Book room', seat: 'Secretary', assignee: 'Demo One' };
  const recording = { title: 'Board meeting', startedAt: '2026-11-19T00:00:00Z', transcription: { text: 'Book a room' } };
  const reply = (meta) => async (_, options) => {
    assert.deepEqual(JSON.parse(options.body), recording);
    return { ok: true, status: 200, json: async () => ({ success: true, data: { assignments: [proposal] }, meta }) };
  };
  await withFetch(reply({ stored: false, store_error: 'Tasks were not saved: the task store is unavailable.' }), async () => {
    const result = await assignRecordingTasks('rec-1', recording);
    assert.equal(result.stored, false);
    assert.match(result.storeError, /not saved/);
    assert.deepEqual(result.assignments, [proposal]);
  });
  await withFetch(reply({ stored: true }), async () => {
    const result = await assignRecordingTasks('rec-1', recording);
    assert.equal(result.stored, true);
    assert.equal(result.storeError, null);
  });
});
