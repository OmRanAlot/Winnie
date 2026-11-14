// Calls to the Winnie backend. Two endpoints so far: GET /api/health and POST /api/recordings
// (which saves the recording JSON and the audio file; returns both filenames).
// Base URL comes from VITE_API_BASE_URL (default "/api", proxied to localhost:8000 by
// vite.config.ts). Backend side: backend/app/routes/health.py and routes/recordings.py.
const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

export async function checkHealth(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBase}/health`, { signal });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data = await response.json();
  if (data.status !== 'ok' || data.service !== 'winnie-api') throw new Error('Unexpected health response');
}

export interface SavedRecording { filename: string; audioFilename: string }

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
  return { filename: result.data.filename, audioFilename: result.data.audioFilename };
}
