// Calls to the Winnie backend: GET /api/health, POST /api/recordings (+ /{id}/assignments), and the
// task timeline (GET /api/tasks, PATCH /api/tasks/{id}/status). POST /api/recordings
// (which saves the recording JSON and the audio file; returns both filenames).
// Base URL comes from VITE_API_BASE_URL (default "/api", proxied to localhost:8000 by
// vite.config.ts). Backend side: backend/app/routes/health.py and routes/recordings.py.
// Accept an origin alone as well as an explicit API path.
const configuredBase = (import.meta.env.VITE_API_BASE_URL || '/api').trim().replace(/\/+$/, '');
const apiBase = /^https?:\/\/[^/]+$/i.test(configuredBase) ? `${configuredBase}/api` : configuredBase;
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

export async function checkHealth(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBase}/health`, { signal });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data = await response.json();
  if (data.status !== 'ok' || data.service !== 'winnie-api') throw new Error('Unexpected health response');
}

export interface SavedRecording { id: string; filename: string; audioFilename: string }

export async function saveRecording(recording: unknown): Promise<SavedRecording> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/recordings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(recording), signal: AbortSignal.timeout(30000),
    });
  } catch { throw new Error('Cannot reach the backend. Start the API on port 8000, or download locally.'); }
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.success) throw new Error(result?.error?.message || `Saving failed (HTTP ${response.status}).`);
  return { id: result.data.id, filename: result.data.filename, audioFilename: result.data.audioFilename };
}

export interface Assignment { title: string; description: string; assignee: string | null; seat: string; deadline: string | null; rationale: string; needs_review: boolean }
export async function assignTasks(id: string): Promise<{data: {assignments: Assignment[]; tasks?: TaskView[]}; meta: {source: string; stored?: boolean; store_error?: string}}> {
  const response = await fetch(`${apiBase}/recordings/${encodeURIComponent(id)}/assignments`, {method: 'POST', signal: AbortSignal.timeout(200000)});
  const result = await response.json();
  if (!response.ok || !result.success) throw new Error(result?.error?.message || 'Task assignment failed');
  return result;
}

// --- Task timeline: GET /api/tasks, PATCH /api/tasks/{id}/status (backend/app/routes/tasks.py) ---
// TaskView mirrors backend/app/schemas.py TaskView. This is the ONLY contract the timeline UI
// depends on, so a replacement frontend just needs these two calls.
export type TaskStatus = 'open' | 'done' | 'blocked';
export interface TaskView {
  id: number; title: string; description: string | null; status: TaskStatus;
  seat: string | null; assignee: string | null; assignee_id: number | null;
  start: string; end: string | null; // ISO 8601; end null = unscheduled
  deadline_raw: string | null; needs_review: boolean; rationale: string | null; depends_on: number[];
}

async function envelope<T>(response: Response, fallback: string): Promise<T> {
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.success) throw new Error(result?.error?.message || `${fallback} (HTTP ${response.status}).`);
  return result.data as T;
}

export async function listTasks(signal?: AbortSignal): Promise<TaskView[]> {
  let response: Response;
  try { response = await fetch(`${apiBase}/tasks`, { signal }); }
  catch (cause) { if (signal?.aborted) throw cause; throw new Error('Cannot reach the backend to load tasks.'); }
  return envelope<TaskView[]>(response, 'Loading tasks failed');
}

export async function setTaskStatus(id: number, status: TaskStatus): Promise<TaskView> {
  const response = await fetch(`${apiBase}/tasks/${id}/status`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
  });
  return envelope<TaskView>(response, 'Updating the task failed');
}
