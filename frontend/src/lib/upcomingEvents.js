// Builds the shared upcoming-events list from tasks, meetings, and (for admins) event plans.

function todayKey(now = new Date()) {
  const local = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return local.toISOString().slice(0, 10);
}

function dateKey(value) {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10);
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return null;
  return new Date(parsed).toISOString().slice(0, 10);
}

function usDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${Number(m)}/${Number(d)}/${y}`;
}

function upsert(map, { key, name, date, kind, sourceId }) {
  const existing = map.get(key) || {
    key, name, date: null, kinds: new Set(), sourceIds: {}, taskCount: 0, openCount: 0,
  };
  if (date && (!existing.date || date < existing.date)) existing.date = date;
  existing.kinds.add(kind);
  if (sourceId) existing.sourceIds[kind] = sourceId;
  map.set(key, existing);
  return existing;
}

export function collectUpcomingEvents({ tasks = [], meetings = [], eventPlans = [], now = new Date() } = {}) {
  const today = todayKey(now);
  const map = new Map();

  for (const task of tasks) {
    const name = (task.event || "").trim();
    if (!name) continue;
    const key = name.toLowerCase();
    const due = dateKey(task.dueIso);
    const entry = upsert(map, { key, name, date: due && due >= today ? due : null, kind: "task" });
    entry.taskCount += 1;
    if (task.status !== "Completed") entry.openCount += 1;
  }

  for (const meeting of meetings) {
    const name = (meeting.name || meeting.title || "").trim();
    if (!name) continue;
    const key = `meeting:${meeting.id || name.toLowerCase()}`;
    const held = dateKey(meeting.held_at) || dateKey(meeting.date);
    if (held && held < today) continue;
    upsert(map, {
      key, name, date: held, kind: "meeting", sourceId: meeting.id,
    });
  }

  for (const plan of eventPlans) {
    if (!plan?.event_name) continue;
    if (plan.status && !["draft", "approved", "pending_approval"].includes(plan.status)) continue;
    const held = dateKey(plan.event_date);
    if (held && held < today) continue;
    const key = plan.event_name.trim().toLowerCase();
    upsert(map, {
      key, name: plan.event_name.trim(), date: held, kind: "plan", sourceId: plan.id,
    });
  }

  return [...map.values()]
    .map((entry) => ({
      key: entry.key,
      name: entry.name,
      date: entry.date,
      dateLabel: entry.date ? usDate(entry.date) : "Date TBD",
      kinds: [...entry.kinds],
      meetingId: entry.sourceIds.meeting || null,
      planId: entry.sourceIds.plan || null,
      taskCount: entry.taskCount,
      openCount: entry.openCount,
    }))
    .sort((a, b) => {
      if (a.date && b.date && a.date !== b.date) return a.date < b.date ? -1 : 1;
      if (a.date && !b.date) return -1;
      if (!a.date && b.date) return 1;
      return a.name.localeCompare(b.name);
    });
}

export function tasksForEvent(tasks, eventName) {
  const key = String(eventName || "").trim().toLowerCase();
  if (!key) return [];
  return tasks.filter((task) => String(task.event || "").trim().toLowerCase() === key);
}
