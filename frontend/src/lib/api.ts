const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export async function checkHealth(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBase}/health`, { signal });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data = await response.json();
  if (data.status !== 'ok' || data.service !== 'winnie-api') {
    throw new Error('Unexpected health response');
  }
}
