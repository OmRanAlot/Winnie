// Admin review of live Google tracker changes; edits and conflicts are explicit before apply.
import { useEffect, useState } from 'react';
import { applySheetSync, getSheetSyncSources, previewSheetSync } from './lib/api.js';

const display = value => value == null || value === '' ? '(empty)' : String(value);

export default function SheetSync({ onApplied }) {
  const [sources, setSources] = useState([]);
  const [key, setKey] = useState('');
  const [plan, setPlan] = useState(null);
  const [resolutions, setResolutions] = useState({});
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const reload = async () => {
    const data = await getSheetSyncSources();
    setSources(data); setKey(current => current || data[0]?.key || '');
  };
  useEffect(() => { reload().catch(e => setError(e.message)).finally(() => setBusy(false)); }, []);
  const run = async action => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const source = sources.find(s => s.key === key);
  const build = () => run(async () => {
    setPlan(null);
    setPlan(await previewSheetSync(key, resolutions));
  });
  return <div className="panel" style={{ maxWidth: 1000, margin: '0 auto' }}>
    <p>Import changes from Google Sheets. Updates made in Winnie are preserved when the sheet cell has not changed. Rows removed from Sheets do not delete tasks.</p>
    {busy && <p role="status">Checking sync…</p>}
    {error && <p role="alert">{error} {!sources.length && <button className="btn alt" disabled={busy} onClick={() => run(reload)}>Retry</button>}</p>}
    {!busy && !sources.length && !error && <p>No tracker sources configured. Follow <code>docs/GOOGLE_SHEETS_SYNC.md</code> to connect a workbook on the server.</p>}
    {!!sources.length && <>
      <label>Tracker <select className="field" disabled={busy} value={key} onChange={e => {
        setKey(e.target.value); setPlan(null); setResolutions({}); setError(''); setMessage('');
      }}>{sources.map(s => <option key={s.key} value={s.key}>{s.key} · {s.semester_code}</option>)}</select></label>
      {source && <p><a href={`https://docs.google.com/spreadsheets/d/${encodeURIComponent(source.spreadsheet_id)}/edit${source.tab_id != null ? `#gid=${source.tab_id}` : ''}`} target="_blank" rel="noreferrer">Open source workbook</a>
        {' · '}{source.tab_name || `Tab gid ${source.tab_id}`}<br />
        Automatic sync: {source.auto_apply ? 'enabled when the sync worker is running' : 'off'}<br />
        Last applied: {source.last_run ? new Date(source.last_run.created_at).toLocaleString() : 'Never'}</p>}
      <button className="btn alt" disabled={busy} onClick={build}>Build Preview</button>
    </>}
    {plan && <>
      <h3>Changes</h3>
      <p>{plan.summary.insert} new · {plan.summary.update} updated · {plan.summary.unchanged} unchanged</p>
      {!!plan.preserved.length && <p>{plan.preserved.length} local field changes preserved.</p>}
      {!!plan.missing_from_sheet.length && <p>{plan.missing_from_sheet.length} existing tasks are absent from this tab and will be kept.</p>}
      {plan.operations.filter(op => op.action !== 'unchanged').map(op => <details key={op.source_task_id}>
        <summary>{op.action === 'insert' ? 'Add' : 'Update'} {op.source_task_id}: {op.values.title || ''}</summary>
        {Object.entries(op.values).map(([field, value]) => <p key={field}><b>{field}</b>: {op.before && `${display(op.before[field])} → `}{display(value)}</p>)}
      </details>)}
      {!!plan.conflicts.length && <>
        <h3>Conflicting edits</h3><p>Choose which value to keep, then rebuild the preview. Automatic sync pauses this tracker until conflicts are resolved.</p>
        {plan.conflicts.map(c => <div key={c.key} style={{ borderTop: '1px solid #ccc', padding: 12 }}>
          <p><b>{c.source_task_id} · {c.field}</b><br />Winnie: {display(c.winnie)}<br />Sheets: {display(c.sheet)}</p>
          <label>Keep value <select className="field" disabled={busy} value={resolutions[c.key] || ''} onChange={e => {
            setResolutions(current => ({ ...current, [c.key]: e.target.value }));
          }}><option value="">Choose…</option><option value="winnie">Keep Winnie</option><option value="sheet">Use Sheets</option></select></label>
        </div>)}
      </>}
      <button className="btn" disabled={busy || !!plan.conflicts.length} onClick={() => run(async () => {
        const summary = await applySheetSync(key, plan.plan_id, resolutions);
        setPlan(null); setResolutions({});
        setMessage(`Sync saved: ${summary.insert} added, ${summary.update} updated.`);
        await reload();
        try { await onApplied?.(); } catch { setMessage('Sync saved. Refresh the dashboard to reload tasks.'); }
      })}>Apply Reviewed Changes</button>
    </>}
    {message && <p role="status">{message}</p>}
  </div>;
}
