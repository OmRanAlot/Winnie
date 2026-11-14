// Calls to the Winnie backend (/api is proxied to localhost:8000 by vite.config.js).
// Backend tasks are translated into the shape App.jsx's design uses, so the screens don't change.

const PAGE = 100; // the backend's maximum page size for GET /api/tasks

const STATUS_TO_UI = { todo: "Upcoming", in_progress: "In-Progress", blocked: "In-Progress", done: "Completed" };
const STATUS_FROM_UI = { Upcoming: "todo", "In-Progress": "in_progress", Completed: "done" };

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
      signal: options.signal ?? AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error("Cannot reach the backend. Is it running on port 8000?");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.success) {
    throw new Error(body?.error?.message || body?.detail || `Request failed (HTTP ${response.status}).`);
  }
  return body;
}

// "2026-12-15" -> "12/15/2026"
const usDate = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}` : "");

// Monday of the current week, at midnight local time.
export function weekStart(today = new Date()) {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

export function toUiTask(t, monday = weekStart()) {
  const due = t.due_date ? new Date(`${t.due_date}T00:00:00`) : null;
  const day = due ? Math.round((due - monday) / 86400000) : -1; // 0 = Monday of this week
  return {
    id: t.id,
    code: t.task_code,
    title: t.title,
    assigned: usDate(t.created_at?.slice(0, 10)),
    start: usDate(t.due_date) || "—",
    due: usDate(t.due_date) || t.deadline_text || "No date",
    dueIso: t.due_date,
    finished: t.status === "done" ? usDate(t.updated_at?.slice(0, 10)) : "",
    assignee: null, // no member mapping in the API yet; assigneeText holds the tracker cell
    assigneeText: t.assignee_text || "",
    status: STATUS_TO_UI[t.status] ?? "Upcoming",
    blocked: t.status === "blocked",
    dep: null, // dependencies are not stored in the backend yet
    day,
    len: 1,
    thisWeek: day >= 0 && day < 7,
    notes: t.description || "",
    event: t.event_tag || t.project_name || "",
  };
}

export async function getTasks() {
  const all = [];
  for (let offset = 0; ; offset += PAGE) {
    const body = await request(`/tasks?limit=${PAGE}&offset=${offset}`);
    all.push(...body.data);
    if (body.data.length < PAGE || all.length >= (body.meta?.total ?? 0)) break;
  }
  const monday = weekStart();
  return all.map((t) => toUiTask(t, monday));
}

// Board members (public fields only), in the shape App.jsx's PEOPLE uses.
export async function getMembers() {
  const body = await request("/members");
  return body.data.map((m) => ({
    id: m.code,
    name: m.display_name,
    role: m.board_role,
    description: m.role_description,
    skills: m.skills ?? [],
  }));
}

// {task id: [member codes]} for the active semester; null = assignee cell not recognized yet.
export async function getAssignments() {
  const body = await request("/members/assignments");
  return { byTask: body.data, meta: body.meta };
}

// Save a meeting recording (audio + transcript JSON, shape = backend schemas.Recording).
export async function saveRecording(recording) {
  const body = await request("/recordings", {
    method: "POST", body: JSON.stringify(recording), signal: AbortSignal.timeout(60000),
  });
  return body.data; // {id, filename, audioFilename}
}

// Ask the backend (Gemini) to pull tasks out of a saved recording's transcript.
export async function assignRecordingTasks(id) {
  const body = await request(`/recordings/${encodeURIComponent(id)}/assignments`, {
    method: "POST", signal: AbortSignal.timeout(200000),
  });
  return body.data.assignments; // [{title, description, seat, assignee, deadline, rationale, needs_review}]
}

export async function updateTaskStatus(id, uiStatus) {
  const status = STATUS_FROM_UI[uiStatus];
  if (!status) throw new Error(`Unknown status ${uiStatus}`);
  const body = await request(`/tasks/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  return toUiTask(body.data);
}
