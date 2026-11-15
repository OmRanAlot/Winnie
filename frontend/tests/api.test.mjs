// Verify dashboard requests use the canonical record API and preserve task UUIDs.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { getTasks, updateTaskStatus } from '../src/lib/api.js';

test('dashboard reads and updates the same UUID task records', async () => {
  const original = globalThis.fetch;
  const id = '11111111-1111-4111-8111-111111111111';
  const calls = [];
  const task = { id, title: 'Synthetic meeting action', task_code: 'WIN-202611-1',
    status: 'todo', created_at: '2026-11-13T23:00:00Z', assignee_text: 'Demo One' };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ success: true,
      data: options.method === 'PATCH' ? { ...task, status: 'in_progress' } : [task],
      meta: { total: 1 } }) };
  };
  try {
    const tasks = await getTasks();
    assert.equal(tasks[0].id, id);
    assert.equal(tasks[0].assigneeText, 'Demo One');
    const updated = await updateTaskStatus(id, 'In-Progress');
    assert.equal(updated.id, id);
    assert.equal(updated.status, 'In-Progress');
    assert.equal(calls[0].url, '/api/tasks/records?limit=250&offset=0');
    assert.equal(calls[1].url, `/api/tasks/records/${id}`);
    assert.deepEqual(JSON.parse(calls[1].options.body), { status: 'in_progress' });
  } finally { globalThis.fetch = original; }
});
