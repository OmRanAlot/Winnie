// Pure Gantt layout for the task timeline: where each bar goes, axis ticks, per-person colors.
// No React and no fetching, so it is unit-tested in tests/timeline.test.mjs and survives a
// redesign. Used by Timeline.tsx. Input is TaskView[] from GET /api/tasks (src/lib/api.ts).
import type { TaskView } from '../../lib/api';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const MIN_BAR_PCT = 1.5; // a task raised and due at the same moment still gets a visible bar

// Distinct, mid-saturation hues; readable with white text and on the light page background.
export const PERSON_COLORS = ['#3b6ea5', '#c8553d', '#3f8f5b', '#8e5ea2', '#b8860b', '#1f8a8a', '#c2577f', '#6b5b3e'];
export const UNASSIGNED_COLOR = '#8a948a';

export const colorFor = (assigneeId: number | null): string =>
  assigneeId == null ? UNASSIGNED_COLOR : PERSON_COLORS[Math.abs(assigneeId) % PERSON_COLORS.length];

export interface Bar { task: TaskView; leftPct: number; widthPct: number; color: string }
export interface Tick { label: string; pct: number }
export interface Person { id: number | null; name: string; color: string }
export interface Timeline { start: number; end: number; bars: Bar[]; unscheduled: TaskView[]; ticks: Tick[]; people: Person[]; nowPct: number | null }

const pct = (time: number, start: number, end: number) => ((time - start) / (end - start)) * 100;

function dayTicks(start: number, end: number): Tick[] {
  const step = end - start > 21 * DAY ? 7 : 1;
  const day = new Date(start); day.setHours(0, 0, 0, 0);
  const ticks: Tick[] = [];
  for (; day.getTime() <= end; day.setDate(day.getDate() + step)) {
    if (day.getTime() >= start) ticks.push({ label: day.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }), pct: pct(day.getTime(), start, end) });
  }
  return ticks;
}

function peopleOf(tasks: TaskView[]): Person[] {
  const seen = new Map<string, Person>();
  for (const task of tasks) {
    const key = task.assignee_id == null ? 'none' : String(task.assignee_id);
    if (!seen.has(key)) seen.set(key, { id: task.assignee_id, name: task.assignee ?? 'Unassigned', color: colorFor(task.assignee_id) });
  }
  return [...seen.values()].sort((a, b) => (a.id == null ? 1 : b.id == null ? -1 : a.name.localeCompare(b.name)));
}

/** Lay out scheduled tasks (with an `end`) as bars ordered by deadline, then start. */
export function buildTimeline(tasks: TaskView[], now: number = Date.now()): Timeline {
  const scheduled = tasks.filter(task => task.end)
    .map(task => ({ task, from: Date.parse(task.start), to: Date.parse(task.end as string) }))
    .sort((a, b) => a.to - b.to || a.from - b.from || a.task.id - b.task.id);
  const unscheduled = tasks.filter(task => !task.end);
  const people = peopleOf(tasks);
  if (!scheduled.length) return { start: now, end: now + DAY, bars: [], unscheduled, ticks: [], people, nowPct: null };

  let start = Math.min(...scheduled.map(s => Math.min(s.from, s.to)));
  let end = Math.max(...scheduled.map(s => Math.max(s.from, s.to)));
  start -= 6 * HOUR; end += 6 * HOUR;
  if (end - start < DAY) end = start + DAY;

  const bars = scheduled.map(({ task, from, to }) => {
    const left = pct(Math.min(from, to), start, end);
    const width = Math.max(pct(Math.max(from, to), start, end) - left, MIN_BAR_PCT);
    return { task, leftPct: Math.min(left, 100 - width), widthPct: width, color: colorFor(task.assignee_id) };
  });
  const nowPct = now >= start && now <= end ? pct(now, start, end) : null;
  return { start, end, bars, unscheduled, ticks: dayTicks(start, end), people, nowPct };
}
