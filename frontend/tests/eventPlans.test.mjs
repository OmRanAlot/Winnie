import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createEventPlan, getEventPlan, getEventPlans, updateEventPlan } from '../src/lib/eventPlans.js';

function useMemoryStorage() {
  const previous = globalThis.localStorage;
  const values = new Map();
  globalThis.localStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
  return () => {
    if (previous === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previous;
  };
}

test('event plans persist in this browser and can be reopened and updated', async () => {
  const restore = useMemoryStorage();
  try {
    const saved = await createEventPlan({
      event_name: 'WiCS Career Panel', description: 'Alumni discussion.',
      event_date: '2027-04-20', event_time: '18:30', plan_text: 'Reserve a room.',
    });
    assert.ok(saved.id);
    assert.equal((await getEventPlan(saved.id)).event_time, '18:30');
    assert.deepEqual((await getEventPlans()).map(plan => plan.id), [saved.id]);

    const updated = await updateEventPlan(saved.id, { plan_text: 'Room reserved.' });
    assert.equal(updated.plan_text, 'Room reserved.');
    assert.equal((await getEventPlan(saved.id)).plan_text, 'Room reserved.');
  } finally { restore(); }
});

test('invalid browser data and missing saved plans are reported', async () => {
  const restore = useMemoryStorage();
  try {
    globalThis.localStorage.setItem('winnie.eventPlans.v1', '{');
    await assert.rejects(getEventPlans(), /browser storage is invalid/);
    globalThis.localStorage.setItem('winnie.eventPlans.v1', '[]');
    await assert.rejects(getEventPlan('missing'), /not found in this browser/);
    await assert.rejects(updateEventPlan('missing', { plan_text: 'No plan.' }), /not found in this browser/);
  } finally { restore(); }
});
