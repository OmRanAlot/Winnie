import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reassignmentStore } from '../src/lib/reassignments.js';
import { getTasks, updateTaskStatus, toUiTask } from '../src/lib/api.js';

test('submission sends only proposal details; the server supplies member identity', async () => {
  const calls = [];
  const store = reassignmentStore({ rpc: async (...args) => {
    calls.push(args);
    return { data: { id: 'request-1', status: 'pending' }, error: null };
  } });
  assert.equal((await store.submit('task-1', 'TARGET', 'Conflict')).status, 'pending');
  assert.deepEqual(calls, [['submit_task_reassignment', {
    p_task_id: 'task-1', p_proposed_assignee_code: 'TARGET', p_reason: 'Conflict',
  }]]);
});

test('approve and deny are persisted via RPC; server rejection stays an error', async () => {
  const calls = [];
  const store = reassignmentStore({ rpc: async (name, args) => {
    calls.push([name, args]);
    if (args.p_request_id === 'stale') return { error: { message: 'Task assignment changed' } };
    return { data: { status: args.p_decision }, error: null };
  } });
  assert.equal((await store.review('one', 'approved')).status, 'approved');
  assert.equal((await store.review('two', 'rejected')).status, 'rejected');
  await assert.rejects(store.review('stale', 'approved'), /assignment changed/);
  assert.throws(() => store.review('one', 'pending'), /Invalid decision/);
  assert.equal(calls.length, 3);
  assert.equal(calls[0][0], 'review_task_reassignment');
  assert.ok(!('reviewed_by_profile_id' in calls[0][1]));
});

test('request history paginates without silently losing pending rows', async () => {
  const offsets = [];
  const chain = {
    select() { return this; }, order() { return this; },
    abortSignal() { return this; },
    async range(start, end) {
      offsets.push([start, end]);
      return { data: Array.from({ length: start === 0 ? 100 : 2 }, (_, i) => ({ id: start + i })), error: null };
    },
  };
  const store = reassignmentStore({ from(name) {
    assert.equal(name, 'task_reassignment_requests'); return chain;
  } });
  assert.equal((await store.list()).length, 102);
  assert.deepEqual(offsets, [[0, 99], [100, 199]]);
});

test('recipient responses send only request and decision; failures stay visible', async () => {
  const calls = [];
  const store = reassignmentStore({ rpc: async (name, args) => {
    calls.push([name, args]);
    return args.p_request_id === 'stale' ? {error:{message:'Request already answered'}} : {data:{recipient_decision:args.p_decision},error:null};
  } });
  assert.equal((await store.respond('one','accepted')).recipient_decision,'accepted');
  assert.equal((await store.respond('two','denied')).recipient_decision,'denied');
  await assert.rejects(store.respond('stale','accepted'),/already answered/);
  assert.throws(() => store.respond('one','approved'),/Invalid response/);
  assert.deepEqual(calls[0],['respond_task_reassignment',{p_request_id:'one',p_decision:'accepted'}]);
});

test('task mapping preserves current and original roster codes', () => {
  const row = toUiTask({ id: 'one', title: 'Task', status: 'todo', owner_code: 'NEW', original_assignee_code: 'OLD' });
  assert.equal(row.ownerCode, 'NEW');
  assert.equal(row.assignee, 'NEW');
  assert.equal(row.originalAssigneeCode, 'OLD');
});

test('task reads and updates use the live UUID records API without caching', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    const data = options.method === 'PATCH'
      ? { id: 'uuid', status: 'done', owner_code: 'NEW', original_assignee_code: 'OLD' }
      : [{ id: 'uuid', status: 'todo', owner_code: 'NEW' }];
    return { ok: true, json: async () => ({ success: true, data, meta: { total: 1 } }) };
  };
  try {
    assert.equal((await getTasks())[0].ownerCode, 'NEW');
    assert.equal((await updateTaskStatus('uuid', 'Completed')).originalAssigneeCode, 'OLD');
    assert.equal(calls[0][0], '/api/tasks/records?limit=100&offset=0');
    assert.equal(calls[1][0], '/api/tasks/records/uuid');
    assert.equal(calls[0][1].cache, 'no-store');
    assert.deepEqual(JSON.parse(calls[1][1].body), { status: 'done' });
  } finally { globalThis.fetch = original; }
});

test('notification enqueue failure preserves the committed reassignment result',async()=>{
 const calls=[];
 const store=reassignmentStore({rpc:async(name,args)=>{calls.push(name);return {data:{id:'saved',status:'pending'},error:null};}},
  {notify:async()=>{throw new Error('Queue temporarily unavailable');}});
 const result=await store.submit('task','TARGET');
 assert.equal(result.id,'saved'); assert.match(result.notification_warning,/Saved/);
 assert.deepEqual(calls,['submit_task_reassignment']);
});
