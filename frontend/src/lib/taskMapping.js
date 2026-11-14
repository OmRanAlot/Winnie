// Turns backend tasks (TaskView, see lib/api.js) into the shapes the UI in App.jsx draws, and the
// UI's three statuses back into the backend's. Pure functions, covered by tests/taskMapping.test.mjs.
//
// UUID task identities and todo/in_progress/blocked/done statuses come from the shared task store.
// A blocked task is drawn as In-Progress until the UI gains a separate blocked state.

const DAY_MS = 86_400_000;
const MIN_BAR_DAYS = 0.6;

export const STATUS_COLORS = { Upcoming: '#e0b25a', 'In-Progress': '#cc6a3d', Completed: '#7a2c22' };

export function uiStatus(view, started = new Set()) {
  if (view.status === 'done') return 'Completed';
  if (view.status === 'in_progress' || view.status === 'blocked' || started.has(view.id)) return 'In-Progress';
  return 'Upcoming';
}

export function backendStatus(status) {
  return status === 'Completed' ? 'done' : status === 'In-Progress' ? 'in_progress' : 'todo';
}

/** ISO timestamp -> "MM/DD/YYYY" in local time ('' when missing or invalid). */
export function formatDate(iso) {
  const date = iso ? new Date(iso) : null;
  if (!date || Number.isNaN(date.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())}/${date.getFullYear()}`;
}

/** Local midnight of the Monday that starts the week containing `now`. */
export function weekStart(now = new Date()) {
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  return monday;
}

/** Column (0 = Mon) and width, in days, of a Gantt bar clamped to the week shown. */
export function barPlacement(startIso, endIso, now = new Date()) {
  const origin = weekStart(now).getTime();
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : start + DAY_MS;
  const clamp = (days) => Math.min(7, Math.max(0, days));
  const first = clamp(((Number.isNaN(start) ? origin : start) - origin) / DAY_MS);
  const last = clamp(((Number.isNaN(end) ? origin + DAY_MS : end) - origin) / DAY_MS);
  const day = Math.min(first, 7 - MIN_BAR_DAYS);
  return { day, len: Math.max(MIN_BAR_DAYS, last - day) };
}

export function toUiTask(view, started = new Set(), now = new Date()) {
  const placement = barPlacement(view.start, view.end, now);
  return {
    id: view.id,
    title: view.title,
    assigned: formatDate(view.start),
    start: formatDate(view.start),
    due: view.end ? formatDate(view.end) : (view.deadline_raw || 'Unscheduled'),
    finished: '', // the API does not record when a task was finished
    assignee: view.assignee_id,
    status: uiStatus(view, started),
    dep: view.depends_on?.[0] ?? null,
    notes: view.rationale || view.description || '',
    ...placement,
  };
}

/** One person per assignee_id found on the tasks; unassigned tasks (null id) are skipped. */
export function peopleFromViews(views) {
  const byId = new Map();
  for (const view of views) {
    if (view.assignee_id == null || byId.has(view.assignee_id)) continue;
    byId.set(view.assignee_id, { id: view.assignee_id, name: view.assignee || 'Unknown', role: view.seat || 'Member', skills: [] });
  }
  return [...byId.values()];
}
