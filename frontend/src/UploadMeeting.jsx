// Prerecorded audio uses the backend's transcription/summary/task-ingestion endpoint.
import { useState } from 'react';
import { ingestMeetingAudio } from './lib/api.js';

export default function UploadMeeting({ onSaved }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState('Board meeting');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function submit(event) {
    event.preventDefault(); if (busy || !file) return;
    if (file.size > 15 * 1024 * 1024) { setError('Choose audio no larger than 15 MB.'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      await ingestMeetingAudio(file, title);
      setNotice('Meeting processed and saved. Extracted tasks are in the task list.');
      try { await onSaved(); } catch { setError('Saved, but refreshing failed. Please refresh the board.'); }
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <form className="panel" onSubmit={submit}><h3>Upload meeting audio</h3>
    <p>Confirm everyone agreed to recording before uploading.</p>
    <label>Meeting title<input className="field" value={title} required maxLength={200} disabled={busy} onChange={e => setTitle(e.target.value)} /></label>
    <label>Audio file<input type="file" accept="audio/*" disabled={busy} onChange={e => setFile(e.target.files?.[0] || null)} /></label>
    <button className="btn" disabled={busy || !file}>{busy ? 'Processing…' : 'Upload and process'}</button>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </form>;
}
