import assert from 'node:assert/strict';
import { test } from 'node:test';
import { staggeredLoads } from '../src/lib/staggeredLoads.js';

test('admin loads start with Plan Event, pace later starts, and limit overlap', async () => {
  const starts = [];
  const releases = [];
  const job = key => ({ key, run: () => new Promise(resolve => {
    starts.push(key); releases.push(resolve);
  }) });
  const stop = staggeredLoads(job('planEvent'), [job('metrics'), job('attendance'), job('sheets')],
    () => {}, { gapMs: 10, maxConcurrent: 2, random: () => 0 });
  try {
    await new Promise(resolve => setTimeout(resolve, 55));
    assert.equal(starts[0], 'planEvent');
    assert.equal(starts.length, 2);
    releases[0]();
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(starts.length, 3);
  } finally { stop(); releases.forEach(resolve => resolve()); }
});
