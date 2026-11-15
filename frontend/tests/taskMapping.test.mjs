import assert from 'node:assert/strict';
import { test } from 'node:test';
import { backendStatus, barPlacement, formatDate, peopleFromViews, toUiTask, uiStatus, weekStart } from '../src/lib/taskMapping.js';

const view = (id, overrides = {}) => ({
  id, title: `Task ${id}`, description: null, status: 'todo', seat: 'Treasurer', assignee: 'Sam', assignee_id: 2,
  start: '2026-11-11T12:00:00', end: '2026-11-13T12:00:00', deadline_raw: 'by Friday', needs_review: false,
  rationale: null, depends_on: [], ...overrides,
});
const WED = new Date(2026, 10, 11, 9, 0); // Wednesday 11 Nov 2026

test('weekStart returns the Monday at local midnight', () => {
  const monday = weekStart(WED);
  assert.deepEqual([monday.getFullYear(), monday.getMonth(), monday.getDate(), monday.getHours()], [2026, 10, 9, 0]);
  assert.equal(weekStart(new Date(2026, 10, 15, 23, 0)).getDate(), 9); // Sunday belongs to the same week
});

test('maps backend statuses to the UI and remembers started tasks', () => {
  assert.equal(uiStatus(view(1)), 'Upcoming');
  assert.equal(uiStatus(view(1), new Set([1])), 'In-Progress');
  assert.equal(uiStatus(view(1, { status: 'blocked' })), 'In-Progress');
  assert.equal(uiStatus(view(1, { status: 'in_progress' })), 'In-Progress');
  assert.equal(uiStatus(view(1, { status: 'done' }), new Set([1])), 'Completed');
});

test('persists all three UI statuses in the canonical task schema', () => {
  assert.equal(backendStatus('Completed'), 'done');
  assert.equal(backendStatus('In-Progress'), 'in_progress');
  assert.equal(backendStatus('Upcoming'), 'todo');
});

test('formats dates as MM/DD/YYYY and tolerates missing values', () => {
  assert.equal(formatDate('2026-11-03T12:00:00'), '11/03/2026');
  assert.equal(formatDate(null), '');
  assert.equal(formatDate('not a date'), '');
});

test('places bars inside the Mon-Sun week and never lets them vanish', () => {
  assert.deepEqual(barPlacement('2026-11-10T00:00:00', '2026-11-12T00:00:00', WED), { day: 1, len: 2 });
  const past = barPlacement('2026-10-01T00:00:00', '2026-10-02T00:00:00', WED);
  assert.equal(past.day, 0);
  assert.ok(past.len >= 0.6);
  const future = barPlacement('2026-12-01T00:00:00', null, WED);
  assert.ok(future.day + future.len <= 7.0001);
  assert.ok(future.len >= 0.6);
});

test('builds a UI task with its first dependency and a readable due date', () => {
  const task = toUiTask(view(5, { depends_on: [3, 4] }), new Set(), WED);
  assert.equal(task.dep, 3);
  assert.equal(task.due, '11/13/2026');
  assert.equal(task.assignee, 2);
  assert.equal(toUiTask(view(6, { end: null }), new Set(), WED).due, 'by Friday');
  assert.equal(toUiTask(view(7, { end: null, deadline_raw: null }), new Set(), WED).due, 'Unscheduled');
});

test('derives one person per assignee and skips unassigned tasks', () => {
  const people = peopleFromViews([view(1), view(2), view(3, { assignee: null, assignee_id: null }), view(4, { assignee_id: 9, assignee: 'Ana', seat: null })]);
  assert.deepEqual(people.map((p) => [p.id, p.name, p.role]), [[2, 'Sam', 'Treasurer'], [9, 'Ana', 'Member']]);
});

test('UUID identities survive mapping and dependency links', () => {
  const id = '11111111-1111-4111-8111-111111111111';
  const parent = '22222222-2222-4222-8222-222222222222';
  const mapped = toUiTask(view(id, { depends_on: [parent], assignee_id: 'DEMO' }));
  assert.equal(mapped.id, id);
  assert.equal(mapped.dep, parent);
  assert.equal(mapped.assignee, 'DEMO');
});
