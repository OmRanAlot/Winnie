// Admin meeting attendance editor, mounted by App; counts use persisted records only.
import { useState } from 'react';
import { createMeeting, saveAttendance } from './lib/api.js';

export default function Attendance({ meetings, members, loading = false, onReload, onSaved }) {
  const [id, setId] = useState('');
  const [draft, setDraft] = useState(null);
  const [title, setTitle] = useState('E-Board Meeting');
  const [date, setDate] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const meeting = meetings.find(m => String(m.id) === id) || meetings[0];
  const selected = draft ?? meeting?.attendees ?? [];
  const run = async (action) => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return <div className="panel" style={{ maxWidth: 820, margin: '0 auto' }}>
    <form onSubmit={e => { e.preventDefault(); run(async () => {
      const created = await createMeeting(title, date);
      setId(String(created.id)); setDraft(null);
      setMessage('Meeting created. Select attendees below.');
      await onReload();
    }); }}>
      <h3>Add a meeting</h3>
      <label>Title <input className="field" value={title} required maxLength={200} disabled={busy} onChange={e => setTitle(e.target.value)} /></label>
      <label>Date <input className="field" type="date" required value={date} disabled={busy} onChange={e => setDate(e.target.value)} /></label>
      <button className="btn alt" disabled={busy || loading || !title.trim()}>Add Meeting</button>
    </form>
    <hr />
    {meeting ? <>
      <label>Meeting <select className="field" value={meeting.id} disabled={busy} onChange={e => {
        setId(e.target.value); setDraft(null); setMessage(''); setError('');
      }}>{meetings.map(m => <option key={m.id} value={m.id}>{m.name} · {m.date}</option>)}</select></label>
      <p>{meeting.attendance_recorded_at ? 'Attendance recorded. Select members to update it.' : 'Attendance has not been recorded yet.'}</p>
      {!members.length && <p role="alert">Load the board roster before saving attendance.</p>}
      <fieldset disabled={busy} style={{ border: 0, padding: 0 }}><legend>Members who attended ({selected.length})</legend>
        <div className="attendance-list">{members.map(m => <label className="attendance-member" key={m.id}>
          <input type="checkbox" checked={selected.includes(m.id)} onChange={e => setDraft(
            e.target.checked ? [...selected, m.id] : selected.filter(code => code !== m.id)
          )} /><span>{m.name} <small>{m.role}</small></span>
        </label>)}</div>
        {selected.filter(code => !members.some(m => m.id === code)).map(code => <p key={code}>Previously recorded member: {code}</p>)}
      </fieldset>
      <button className="btn" disabled={busy || loading || !members.length} onClick={() => run(async () => {
        const saved = await saveAttendance(meeting.id, selected);
        onSaved(meeting.id, saved.attendees);
        setDraft(null); setMessage('Attendance saved.');
      })}>{busy ? 'Saving…' : 'Save Attendance'}</button>
    </> : <p>No meetings yet. Add a meeting to record attendance.</p>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
  </div>;
}
