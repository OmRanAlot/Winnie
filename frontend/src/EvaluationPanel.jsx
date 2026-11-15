// Real observed metrics plus persisted administrator feedback, without invented scores.
import { useEffect, useState } from 'react';
import { getEvaluation, saveEvaluation } from './lib/api.js';
import { memberMetrics } from './lib/metrics.js';

export default function EvaluationPanel({ member, tasks, meetings, requests, meetingsUnavailable }) {
  const [comments, setComments] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    getEvaluation(member.id).then(data => { if (active) { setComments(data.comments); setLoaded(true); } })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [member.id]);
  async function save(event) {
    event.preventDefault(); if (busy || !loaded) return;
    setBusy(true); setError(''); setNotice('');
    try { await saveEvaluation(member.id, comments); setNotice('Evaluation feedback saved.'); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  const m = memberMetrics(member.id, tasks, meetings, requests);
  const percent = value => value == null ? 'Not enough recorded data' : `${value}%`;
  return <>
    <div className="two"><div className="panel"><h3>Observed task completion</h3>
      <p>{m.completed} of {m.total} assigned tasks completed</p><p>{percent(m.completion)}</p>
      <p>On time: {percent(m.onTime)} ({m.timedCompletions} completions with recorded times)</p></div>
      <div className="panel"><h3>Attendance and handoffs</h3>
        <p>Attendance: {meetingsUnavailable ? 'Meeting data unavailable' : `${percent(m.attendance)} · ${m.attended}/${m.recordedMeetings} recorded meetings`}</p>
        <p>Approved reassignment requests: {m.transfers}</p></div></div>
    <p>These are activity measures, not an overall performance rating. Older completion timestamps may be unavailable.</p>
    <form onSubmit={save} className="panel"><h3>Admin comments</h3>
      {loading && <p role="status">Loading feedback…</p>}
      <textarea className="field" aria-label="Admin comments" value={comments} maxLength={10000}
        disabled={loading || busy || !loaded} onChange={e => setComments(e.target.value)} />
      <button className="btn" disabled={loading || busy || !loaded}>{busy ? 'Saving…' : 'Save evaluation'}</button>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    </form>
  </>;
}
