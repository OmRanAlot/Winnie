// Calls to the Winnie backend (all responses use the {success, data, error, meta} envelope):
//   GET   /api/health                       checkHealth
//   GET   /api/tasks                        listTasks (backend/app/routes/tasks.py)
//   PATCH /api/tasks/{id}/status            setTaskStatus  body {"status": "open"|"done"|"blocked"}
//   POST  /api/recordings                   saveRecording  (backend/app/routes/recordings.py)
//   POST  /api/recordings/{id}/assignments  assignTasks    (Gemini extracts + stores the tasks)
// Base URL comes from VITE_API_BASE_URL (default "/api", proxied to localhost:8000 by vite.config.js).
//
// A task from the API (TaskView, backend/app/schemas/api.py) looks like:
//   { id, title, description, status, seat, assignee, assignee_id, start, end, deadline_raw,
//     needs_review, rationale, depends_on: [ids] }

// Accept an origin alone as well as an explicit API path.
const configuredBase = (import.meta.env?.VITE_API_BASE_URL || '/api').trim().replace(/\/+$/, '');
const apiBase = /^https?:\/\/[^/]+$/i.test(configuredBase) ? `${configuredBase}/api` : configuredBase;

export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

async function unwrap(response, fallback) {
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.success) throw new Error(result?.error?.message || `${fallback} (HTTP ${response.status}).`);
  return result;
}

export async function checkHealth(signal) {
  const response = await fetch(`${apiBase}/health`, { signal });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data = await response.json();
  if (data.status !== 'ok' || data.service !== 'winnie-api') throw new Error('Unexpected health response');
}

export async function listTasks(signal) {
  let response;
  try { response = await fetch(`${apiBase}/tasks`, { signal }); }
  catch (cause) { if (signal?.aborted) throw cause; throw new Error('Cannot reach the backend to load tasks.'); }
  return (await unwrap(response, 'Loading tasks failed')).data;
}

export async function setTaskStatus(id, status) {
  let response;
  try {
    response = await fetch(`${apiBase}/tasks/${id}/status`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
    });
  } catch { throw new Error('Cannot reach the backend to update the task.'); }
  return (await unwrap(response, 'Updating the task failed')).data;
}

export async function saveRecording(recording) {
  let response;
  try {
    response = await fetch(`${apiBase}/recordings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(recording), signal: AbortSignal.timeout(30000),
    });
  } catch { throw new Error('Cannot reach the backend. Start the API on port 8000.'); }
  const { data } = await unwrap(response, 'Saving failed');
  return { id: data.id, filename: data.filename, audioFilename: data.audioFilename };
}

export async function assignTasks(recordingId) {
  const response = await fetch(`${apiBase}/recordings/${encodeURIComponent(recordingId)}/assignments`, {
    method: 'POST', signal: AbortSignal.timeout(200000),
  });
  return unwrap(response, 'Task assignment failed');
}
