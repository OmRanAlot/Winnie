// Task timeline (Gantt): every stored task as a bar from when it was raised to its deadline,
// one color per assignee, unscheduled tasks listed below. Checkbox marks a task done.
//
// PLACEHOLDER UI. Self-contained on purpose: it talks to the backend only through listTasks /
// setTaskStatus in src/lib/api.ts (GET /api/tasks, PATCH /api/tasks/{id}/status) and lays out
// bars with the pure helpers in ./layout.ts. To replace it, delete this folder and the one
// <Timeline /> line in App.tsx; the backend contract (schemas.TaskView) stays the same.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { listTasks, setTaskStatus, type TaskView } from '../../lib/api';
import { buildTimeline } from './layout';
import './timeline.css';

const REFRESH_MS = 10_000;
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

interface TimelineProps { refreshKey?: number }
interface TaskCheckProps { task: TaskView; busy: boolean; onToggle: (task: TaskView) => void }

function TaskCheck({ task, busy, onToggle }: TaskCheckProps) {
  const done = task.status === 'done';
  return <input type="checkbox" className="tl-check" checked={done} disabled={busy} aria-busy={busy} aria-label={`Mark "${task.title}" ${done ? 'open' : 'done'}`} onChange={() => onToggle(task)} />;
}

export default function Timeline({ refreshKey = 0 }: TimelineProps) {
  const [tasks, setTasks] = useState<TaskView[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [pending, setPending] = useState<ReadonlySet<number>>(new Set());
  // Bumped on every toggle: a poll that started before a toggle must not overwrite its result.
  const version = useRef(0);

  const load = useCallback(async (signal?: AbortSignal) => {
    const startedAt = version.current;
    try {
      const fresh = await listTasks(signal);
      if (version.current === startedAt) { setTasks(fresh); setLoadError(''); }
    } catch (cause) { if (!signal?.aborted) setLoadError(cause instanceof Error ? cause.message : 'Could not load tasks.'); }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load(controller.signal); }, REFRESH_MS);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load, refreshKey]);

  const toggle = useCallback(async (task: TaskView) => {
    const status = task.status === 'done' ? 'open' : 'done';
    version.current += 1;
    setActionError('');
    setPending(current => new Set(current).add(task.id)); // checkbox disabled until the PATCH settles
    setTasks(current => current?.map(t => (t.id === task.id ? { ...t, status } : t)) ?? null); // optimistic
    try {
      const saved = await setTaskStatus(task.id, status);
      setTasks(current => current?.map(t => (t.id === saved.id ? saved : t)) ?? null);
    } catch (cause) {
      setTasks(current => current?.map(t => (t.id === task.id ? task : t)) ?? null); // roll back
      setActionError(`“${task.title}” was not updated: ${cause instanceof Error ? cause.message : 'unknown error'}`);
    } finally {
      version.current += 1;
      setPending(current => { const next = new Set(current); next.delete(task.id); return next; });
    }
  }, []);

  const timeline = useMemo(() => buildTimeline(tasks ?? []), [tasks]);
  const colorOf = (task: TaskView) => timeline.people.find(p => p.id === task.assignee_id)?.color;

  return <section className="tl" aria-labelledby="tl-heading">
    <div className="tl-head">
      <div><div className="eyebrow">BOARD TIMELINE</div><h2 id="tl-heading">Who's doing what, by when</h2></div>
      <span className="tl-count">{tasks ? `${tasks.length} task${tasks.length === 1 ? '' : 's'}` : 'Loading…'}</span>
    </div>
    {loadError && <p className="message error" role="alert">{loadError}</p>}
    {actionError && <p className="message error" role="alert">{actionError}</p>}
    {timeline.people.length > 0 && <ul className="tl-legend" aria-label="Assignee colors">
      {timeline.people.map(p => <li key={p.id ?? 'none'}><span className="tl-swatch" style={{ background: p.color }} />{p.name}</li>)}
    </ul>}
    {tasks && !tasks.length && <p className="tl-empty">No tasks yet. Record a meeting and its action items land here.</p>}

    {timeline.bars.length > 0 && <div className="tl-chart" role="list">
      <div className="tl-axis" aria-hidden="true">
        {timeline.ticks.map(t => <span key={t.pct} style={{ left: `${t.pct}%` }}>{t.label}</span>)}
      </div>
      {timeline.bars.map(({ task, leftPct, widthPct, color }) =>
        <div key={task.id} role="listitem" className={`tl-row is-${task.status}`}>
          <div className="tl-label">
            <TaskCheck task={task} busy={pending.has(task.id)} onToggle={toggle} />
            <div><strong>{task.title}</strong><small>{task.assignee ?? 'Unassigned'}{task.seat ? ` · ${task.seat}` : ''}</small></div>
          </div>
          <div className="tl-track">
            {timeline.ticks.map(t => <i key={t.pct} className="tl-grid" style={{ left: `${t.pct}%` }} />)}
            {timeline.nowPct != null && <i className="tl-now" style={{ left: `${timeline.nowPct}%` }} title="Now" />}
            <div className="tl-bar" style={{ left: `${leftPct}%`, width: `${widthPct}%`, background: color }}
              title={`${task.title}\n${task.assignee ?? 'Unassigned'}\nDue ${when(task.end as string)} (said: “${task.deadline_raw}”)${task.status !== 'open' ? `\nStatus: ${task.status}` : ''}`}>
              <span>Due {when(task.end as string)}</span>
            </div>
          </div>
        </div>)}
    </div>}

    {timeline.unscheduled.length > 0 && <div className="tl-unscheduled">
      <h3>Unscheduled <small>no deadline Winnie could read, so a person should set one</small></h3>
      <ul>{timeline.unscheduled.map(task => <li key={task.id} className={`is-${task.status}`}>
        <TaskCheck task={task} busy={pending.has(task.id)} onToggle={toggle} />
        <span className="tl-swatch" style={{ background: colorOf(task) }} />
        <strong>{task.title}</strong>
        <small>{task.assignee ?? 'Unassigned'}{task.deadline_raw ? ` · said “${task.deadline_raw}”` : ''}{task.needs_review ? ' · needs review' : ''}</small>
      </li>)}</ul>
    </div>}
  </section>;
}
