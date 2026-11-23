// Calls to the Winnie backend (/api is proxied to localhost:8000 by vite.config.js).
// Backend tasks are translated into the shape App.jsx's design uses, so the screens don't change.

import { authHeaders } from './authToken.js';
const PAGE = 250; // the backend's maximum page size for GET /api/tasks/records

export async function getSheetSyncSources() {
  return (await request('/sheet-sync/sources')).data;
}

export async function dispatchPhotonNotifications() {
  return (await request('/photon/dispatch', { method: 'POST' })).data;
}

export async function nudgeTask(id) {
  return (await request(`/notifications/tasks/${encodeURIComponent(id)}/nudge`, { method: 'POST' })).data;
}
export async function getAutomationStatus() {
  return (await request('/automation/status', {signal: AbortSignal.timeout(30000)})).data;
}

export async function previewSheetSync(source, resolutions = {}) {
  return (await request(`/sheet-sync/${encodeURIComponent(source)}/preview`, {
    method: 'POST', body: JSON.stringify({ resolutions }), signal: AbortSignal.timeout(90000),
  })).data;
}

export async function applySheetSync(source, expected_plan, resolutions = {}) {
  return (await request(`/sheet-sync/${encodeURIComponent(source)}/apply`, {
    method: 'POST', body: JSON.stringify({ expected_plan, resolutions }), signal: AbortSignal.timeout(90000),
  })).data;
}

const STATUS_TO_UI = { todo: "Upcoming", in_progress: "In-Progress", blocked: "In-Progress", done: "Completed" };
const STATUS_FROM_UI = { Upcoming: "todo", "In-Progress": "in_progress", Completed: "done" };
const apiBase = (import.meta.env?.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

// Firebase Hosting cuts proxied requests off at 60 seconds; the backend may still finish.
const GATEWAY_MESSAGES = {
  504: "The server took too long to answer. It may still finish: refresh the board in a minute before trying again.",
  502: "The server is temporarily unavailable. Please try again in a moment.",
  503: "The server is temporarily unavailable. Please try again in a moment.",
};

export async function request(path, options = {}) {
  const method = (options.method ?? "GET").toUpperCase();
  const endpoint = `${apiBase}${path.split("?")[0]}`;
  let response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      cache: "no-store",
      ...options,
      headers: { ...(typeof FormData !== 'undefined' && options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...await authHeaders(), ...options.headers },
      signal: options.signal ?? AbortSignal.timeout(15000),
    });
  } catch (cause) {
    if (cause?.name === "TimeoutError" || cause?.name === "AbortError") {
      throw new Error(`${method} ${endpoint} took too long to respond. Please try again.`);
    }
    throw new Error(`Cannot reach the server for ${method} ${endpoint}. Check your connection and try again.`);
  }
  const body = await response.json().catch(() => null);
  if (!body && GATEWAY_MESSAGES[response.status]) {
    // Hosting/load-balancer pages are HTML, not our JSON envelope.
    throw new Error(GATEWAY_MESSAGES[response.status]);
  }
  if (!response.ok || !body?.success) {
    const raw = body?.error?.message || body?.detail;
    const detail = Array.isArray(raw) ? raw.map(e => `${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ') : raw;
    throw new Error(`${method} ${endpoint} returned HTTP ${response.status}${detail ? `: ${detail}` : ""}.`);
  }
  return body;
}

// "2026-12-15" -> "12/15/2026"
const usDate = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}` : "");

// Give tasks without an explicit start date a useful Gantt span. Date-only
// arithmetic avoids timezone shifts when the API returns YYYY-MM-DD values.
export function defaultTaskStartDate(dueIso, today = new Date()) {
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (!dueIso || !/^\d{4}-\d{2}-\d{2}$/.test(dueIso)) return todayIso;
  const todayDay = Date.parse(`${todayIso}T00:00:00Z`);
  const dueDay = Date.parse(`${dueIso}T00:00:00Z`);
  if (!Number.isFinite(dueDay) || dueDay <= todayDay) return dueIso;
  const daysUntilDue = (dueDay - todayDay) / 86400000;
  if (daysUntilDue < 7) return todayIso;
  const start = new Date(dueDay - 7 * 86400000);
  return `${start.getUTCFullYear()}-${String(start.getUTCMonth() + 1).padStart(2, "0")}-${String(start.getUTCDate()).padStart(2, "0")}`;
}

// Monday of the current week, at midnight local time.
export function weekStart(today = new Date()) {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

export function toUiTask(t, monday = weekStart()) {
  const due = t.due_date ? new Date(`${t.due_date}T00:00:00`) : null;
  const day = due ? Math.round((due - monday) / 86400000) : -1; // 0 = Monday of this week
  const startIso = t.start_date || defaultTaskStartDate(t.due_date);
  const ownerCode = t.current_assignee_code ?? t.owner_code ?? null;
  const originalAssigneeCode = t.original_assignee_code ?? t.initial_assignee_code ?? t.owner_code ?? null;
  return {
    id: t.id,
    code: t.task_code,
    ownerCode,
    originalAssigneeCode,
    title: t.title,
    assigned: usDate(t.created_at?.slice(0, 10)),
    start: usDate(startIso) || "—",
    startIso,
    dueTime: t.due_time?.slice(0, 5) || '',
    due: usDate(t.due_date) || t.deadline_text || "No date",
    dueIso: t.due_date,
    finished: t.completed_at ? usDate(t.completed_at.slice(0, 10)) : "",
    completedAt: t.completed_at || null,
    updatedAt: t.updated_at || null,
    meetingId: t.source_meeting_id ?? null,
    assignee: ownerCode,
    currentAssignee: ownerCode,
    initialAssignee: originalAssigneeCode,
    assigneeText: t.assignee_text || "",
    status: STATUS_TO_UI[t.status] ?? "Upcoming",
    priority: t.priority ?? "normal",
    blocked: t.status === "blocked",
    dep: null, // Filled from the persisted dependency graph during refresh.
    day,
    len: 1,
    thisWeek: day >= 0 && day < 7,
    description: t.description || "",
    notes: t.notes || "",
    event: t.event_tag || t.project_name || "",
  };
}

export async function getTasks({ updatedSince, onPage } = {}) {
  const all = [];
  const params = new URLSearchParams({ limit: String(PAGE) });
  if (updatedSince) params.set('updated_since', updatedSince);
  for (let offset = 0; ; offset += PAGE) {
    const body = await request(`/tasks/records?${params}&offset=${offset}`);
    all.push(...body.data);
    onPage?.(all.length, body.meta?.total ?? all.length);
    if (body.data.length < PAGE || (body.meta?.total != null && all.length >= body.meta.total)) break;
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
    role: m.board_role === "PR Chair" ? "Public Relations Chair" : m.board_role,
    description: m.role_description,
    skills: m.skills ?? [],
    technical: m.technical_skills ?? [],
    soft: m.soft_skills ?? [],
    previousRoles: m.previous_roles ?? [],
    previousRoleSkills: m.previous_role_skills ?? [],
    manualPreviousRoleSkills: m.previous_role_skills_manual ?? [],
    personalSkills: m.skills_source === 'supabase' ? m.skills : [],
    skillsSource: m.skills_source ?? null, // "role-derived" = generated from the role text
  }));
}

export async function getBoardRoster(signal) {
  return (await request('/members/roster', { signal })).data;
}

export async function addBoardMember(fields) {
  return (await request('/members/roster', { method: 'POST', body: JSON.stringify(fields) })).data;
}

export async function updateBoardMember(code, fields) {
  return (await request(`/members/roster/${encodeURIComponent(code)}`, {
    method: 'PATCH', body: JSON.stringify(fields),
  })).data;
}

/** Returns `{ data, meta }` — both are needed for the board-phone panel. */
export async function getMessagingContacts(signal) {
  const body = await request('/members/messaging-contacts', { signal });
  return { data: body.data, meta: body.meta };
}

export async function syncMessagingContacts({ enrollPhoton = true, rotateAcrossLines = true } = {}) {
  const body = await request('/members/messaging-contacts/sync', {
    method: 'POST',
    body: JSON.stringify({
      enroll_photon: enrollPhoton,
      rotate_across_lines: rotateAcrossLines,
    }),
  });
  return { data: body.data, meta: body.meta };
}

export async function getMeetings() {
  return (await request('/meetings')).data.map((m) => ({
    ...m, name: m.title || 'E-Board Meeting',
    date: new Date(m.held_at).toLocaleDateString('en-US', { timeZone: 'America/New_York' }),
  }));
}

export async function createMeeting(title, meeting_date) {
  return (await request('/meetings', {
    method: 'POST', body: JSON.stringify({ title, meeting_date }),
  })).data;
}

export async function saveAttendance(id, attendees) {
  return (await request(`/meetings/${encodeURIComponent(id)}/attendance`, {
    method: 'PATCH', body: JSON.stringify({ attendees }),
  })).data;
}

// Up to 3 members whose skills fit a pending task, lightest workload first (never the assignee).
// [{code, name, role, fit: "strong"|"possible", reason, matched_skills, open, due_this_week}]
export async function getCandidates(taskId) {
  const body = await request(`/members/candidates/${encodeURIComponent(taskId)}`, {
    signal: AbortSignal.timeout(60000),
  });
  return body.data;
}

export async function getCurrentUser(signal) {
  return (await request('/auth/me', { signal })).data;
}

export async function getDependencies() { return (await request('/dashboard/dependencies')).data; }
export async function saveTaskDependencies(edges) {
  return (await request('/tasks/records/dependencies', {
    method: 'POST',
    body: JSON.stringify({ edges: edges.map(({ task_id, depends_on_id }) => ({ task_id, depends_on_id })) }),
  })).data;
}
export async function saveTaskNotes(id, notes) {
  return (await request(`/tasks/records/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ notes }) })).data;
}
export async function getEvaluation(code) { return (await request(`/dashboard/evaluations/${encodeURIComponent(code)}`)).data; }
export async function saveEvaluation(code, comments) {
  return (await request(`/dashboard/evaluations/${encodeURIComponent(code)}`, { method: 'PUT', body: JSON.stringify({ comments }) })).data;
}
export async function getTaskDraft() { return (await request('/dashboard/draft')).data; }
export async function saveTaskDraft(form) {
  return (await request('/dashboard/draft', { method: 'PUT', body: JSON.stringify(form) })).data;
}
export async function ingestMeetingAudio(file, title) {
  const form = new FormData(); form.append('file', file); form.append('title', title);
  return (await request('/meetings/ingest', { method: 'POST', body: form, signal: AbortSignal.timeout(200000) })).data;
}

export async function reviewHelpRequests() {
  return (await request("/help-requests")).data;
}

export async function decideHelpRequest(number, revision, action) {
  return (await request(`/help-requests/${number}/decision`, {
    method: "POST", body: JSON.stringify({ revision, action }),
  })).data;
}

// {task id: [member codes]} for the active semester; null = assignee cell not recognized yet.
export async function getAssignments() {
  const body = await request("/members/assignments");
  return { byTask: body.data, meta: body.meta };
}

export async function generateTaskPlan(input) {
  const signal = AbortSignal.timeout(90000);
  try {
    const body = await request("/planning/drafts", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    });
    return body.data;
  } catch (error) {
    if (signal.aborted) {
      throw new Error("Planning took too long. Please try again or choose Enter Manually.");
    }
    throw error;
  }
}

export async function createTaskRecord(task) {
  const body = await request("/tasks/records", { // POST /api/tasks does not exist (405)
    method: "POST",
    body: JSON.stringify(task),
  });
  return toUiTask(body.data);
}

// Save a meeting recording (audio + transcript JSON, shape = backend schemas.Recording).
export async function saveRecording(recording) {
  const body = await request("/recordings", {
    method: "POST", body: JSON.stringify(recording), signal: AbortSignal.timeout(60000),
  });
  return body.data; // {id, filename, audioFilename}
}

// Ask the backend (Gemini) to pull tasks out of a saved recording's transcript.
export async function assignRecordingTasks(id, recording) {
  const body = await request(`/recordings/${encodeURIComponent(id)}/assignments`, {
    method: "POST",
    body: JSON.stringify({
      title: recording.title,
      startedAt: recording.startedAt,
      transcription: recording.transcription,
    }),
    signal: AbortSignal.timeout(200000),
  });
  return { // assignments: [{title, description, seat, assignee, deadline, rationale, needs_review}]
    assignments: body.data.assignments ?? [],
    stored: body.meta?.stored === true,
    storeError: body.meta?.store_error ?? null,
  };
}

// {[task_id]: "AI-generated label"} for tasks passed as [{id, title, description}]
export async function getEventLabels(tasks) {
  const body = await request("/tasks/records/event-labels", {
    method: "POST",
    body: JSON.stringify({ tasks }),
    signal: AbortSignal.timeout(30000),
  });
  return body.data; // {[id]: label}
}

export async function updateTaskStatus(id, uiStatus) {
  const status = STATUS_FROM_UI[uiStatus];
  if (!status) throw new Error(`Unknown status ${uiStatus}`);
  const body = await request(`/tasks/records/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  return toUiTask(body.data);
}

// Kept for lib/useRecorder.js and lib/recordingUpload.js.
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

export async function assignTasks(recordingId) {
  const body = await request(`/recordings/${encodeURIComponent(recordingId)}/assignments`, {
    method: "POST", signal: AbortSignal.timeout(200000),
  });
  return body;
}
