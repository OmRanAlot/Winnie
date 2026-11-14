const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

export async function checkHealth(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBase}/health`, { signal });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data = await response.json();
  if (data.status !== 'ok' || data.service !== 'winnie-api') throw new Error('Unexpected health response');
}

export async function saveRecording(recording: unknown): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/recordings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(recording), signal: AbortSignal.timeout(30000),
    });
  } catch { throw new Error('Cannot reach the backend. Start the API on port 8000, or download locally.'); }
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.success) throw new Error(result?.error?.message || `Saving failed (HTTP ${response.status}).`);
  return result.data.filename;
}
