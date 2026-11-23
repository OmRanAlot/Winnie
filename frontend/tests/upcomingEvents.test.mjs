import assert from 'node:assert/strict';
import { test } from 'node:test';
import { collectUpcomingEvents, tasksForEvent } from '../src/lib/upcomingEvents.js';

test('collectUpcomingEvents merges task tags, future meetings, and event plans', () => {
  const now = new Date('2026-11-22T15:00:00');
  const events = collectUpcomingEvents({
    now,
    tasks: [
      { event: 'GirlHacks', dueIso: '2026-12-01', status: 'Upcoming' },
      { event: 'GirlHacks', dueIso: '2026-11-10', status: 'Completed' },
      { event: '', dueIso: '2026-12-02', status: 'Upcoming' },
    ],
    meetings: [
      { id: 'm1', name: 'E-Board Sync', held_at: '2026-11-30T17:00:00Z' },
      { id: 'm0', name: 'Past Sync', held_at: '2026-11-01T17:00:00Z' },
    ],
    eventPlans: [
      { id: 'p1', event_name: 'Spring Workshop', event_date: '2027-03-15', status: 'draft' },
      { id: 'p0', event_name: 'Old Gala', event_date: '2026-01-01', status: 'approved' },
    ],
  });
  assert.deepEqual(events.map((item) => item.name), ['E-Board Sync', 'GirlHacks', 'Spring Workshop']);
  const girlhacks = events.find((item) => item.name === 'GirlHacks');
  assert.equal(girlhacks.openCount, 1);
  assert.equal(girlhacks.taskCount, 2);
});

test('tasksForEvent matches case-insensitively', () => {
  const tasks = [
    { id: '1', event: 'GirlHacks' },
    { id: '2', event: 'girlhacks' },
    { id: '3', event: 'WiCS Gala' },
  ];
  assert.deepEqual(tasksForEvent(tasks, 'GIRLHACKS').map((item) => item.id), ['1', '2']);
});