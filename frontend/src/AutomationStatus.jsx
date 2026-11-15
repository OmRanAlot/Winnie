// Administrator visibility into the scheduled jobs and durable notification queues.
import { useEffect, useState } from 'react';
import { getAutomationStatus } from './lib/api.js';

export default function AutomationStatus() {
  const [data, setData] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true); setError('');
    try { setData(await getAutomationStatus()); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);
  const uncertain = Object.values(data?.notifications || {}).reduce((n, value) => n + (value.uncertain || 0), 0);
  const pending = Object.values(data?.notifications || {}).reduce((n, value) => n + (value.pending || 0), 0);
  return <section className="panel" style={{maxWidth:920,margin:'24px auto'}}>
    <h3>Automation and notifications</h3>
    <button className="btn alt" disabled={busy} onClick={load}>{busy ? 'Checking…' : 'Refresh automation status'}</button>
    {error && <p role="alert">{error}</p>}
    {data && <>
      <p>Cloud delivery: {data.photon_enabled && data.notifications_enabled ? 'enabled' : 'disabled'} · Deadline scans: {data.reminders_enabled ? 'enabled' : 'disabled'} · Scheduler identity: {data.scheduler_configured ? 'configured' : 'not configured'}</p>
      <p>{pending} pending notifications · {uncertain} sends need review. Pending messages require a linked, opted-in recipient. Uncertain sends are not automatically repeated.</p>
      {data.jobs?.length ? data.jobs.map(job => <p key={job.key}>
        <b>{job.key}</b>: {job.status} · {new Date(job.finished_at || job.started_at).toLocaleString()}
        {job.status === 'conflict' && ' — review conflicting changes in Google Sheets Sync.'}
        {job.status === 'failed' && ' — check server configuration and retry the scheduled job.'}
      </p>) : <p>Scheduled jobs have not reported a run yet.</p>}
    </>}
  </section>;
}
