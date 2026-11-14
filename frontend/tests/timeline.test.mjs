import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildTimeline, colorFor, PERSON_COLORS, UNASSIGNED_COLOR } from '../src/features/timeline/layout.ts';

const task = (id, overrides = {}) => ({
  id, title: `Task ${id}`, description: null, status: 'open', seat: 'Treasurer', assignee: 'Sam', assignee_id: 2,
  start: '2026-11-13T18:00:00-05:00', end: '2026-11-16T12:00:00-05:00', deadline_raw: 'by Monday noon',
  needs_review: false, rationale: null, depends_on: [], ...overrides,
});

test('orders bars by deadline and separates unscheduled tasks', () => {
  const tl = buildTimeline([
    task(1),
    task(2, { end: null, deadline_raw: 'soon' }),
    task(3, { end: '2026-11-13T21:00:00-05:00' }),
  ], 0);
  assert.deepEqual(tl.bars.map(b => b.task.id), [3, 1]);
  assert.deepEqual(tl.unscheduled.map(t => t.id), [2]);
});

test('bars sit inside the range and keep a minimum width', () => {
  const tl = buildTimeline([task(1), task(2, { start: '2026-11-16T12:00:00-05:00' })], 0);
  for (const bar of tl.bars) {
    assert.ok(bar.leftPct >= 0 && bar.leftPct + bar.widthPct <= 100.0001);
    assert.ok(bar.widthPct >= 1.5);
  }
  assert.ok(tl.ticks.length >= 3);
});

test('same person always gets the same color, unassigned gets gray', () => {
  assert.equal(colorFor(2), colorFor(2));
  assert.notEqual(colorFor(1), colorFor(2));
  assert.equal(colorFor(null), UNASSIGNED_COLOR);
  assert.equal(colorFor(PERSON_COLORS.length + 1), colorFor(1));
});

test('legend lists each person once with unassigned last', () => {
  const tl = buildTimeline([
    task(1, { assignee: 'Sam', assignee_id: 2 }),
    task(2, { assignee: null, assignee_id: null }),
    task(3, { assignee: 'Alice', assignee_id: 5 }),
    task(4, { assignee: 'Sam', assignee_id: 2 }),
  ], 0);
  assert.deepEqual(tl.people.map(p => p.name), ['Alice', 'Sam', 'Unassigned']);
});

test('now marker only shows inside the range', () => {
  assert.equal(buildTimeline([task(1)], 0).nowPct, null);
  const inside = buildTimeline([task(1)], Date.parse('2026-11-14T12:00:00-05:00')).nowPct;
  assert.ok(inside > 0 && inside < 100);
});

test('empty input yields an empty chart', () => {
  const tl = buildTimeline([], 0);
  assert.equal(tl.bars.length, 0);
  assert.equal(tl.people.length, 0);
});
