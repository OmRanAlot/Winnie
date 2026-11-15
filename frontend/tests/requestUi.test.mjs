import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, rm, mkdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('..', import.meta.url));
await mkdir(path.join(root, 'node_modules/.cache'), { recursive: true });
const temp = await mkdtemp(path.join(root, 'node_modules/.cache/request-ui-'));
after(() => rm(temp, { recursive: true, force: true }));
const output = path.join(temp, 'app.mjs');
await build({
  entryPoints: [path.join(root, 'src/App.jsx')], outfile: output,
  bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', external: ['react', 'react/jsx-runtime'],
  plugins: [{ name: 'fake-services', setup(build) {
    build.onResolve({ filter: /^\.\/lib\/(api\.js|supabase(?:\.js)?|reassignments\.js)$/ }, args => ({ path: args.path, namespace: 'fake' }));
    build.onResolve({ filter: /^\.\/(Recorder|SheetSync)\.jsx$/ }, args => ({ path: args.path, namespace: 'fake' }));
    build.onLoad({ filter: /.*/, namespace: 'fake' }, args => ({ contents:
      args.path.includes('api.js') ? `
        export const getTasks = () => Promise.resolve(globalThis.__dashboard.tasks);
        export const getMembers = () => Promise.resolve(globalThis.__dashboard.people);
        export const getAssignments = () => Promise.resolve({byTask: {task1: [globalThis.__dashboard.tasks[0].ownerCode]}});
        export const weekStart = () => new Date('2026-11-09T00:00:00');
        export const getCandidates = () => Promise.resolve([]);
        export const updateTaskStatus = () => Promise.resolve();
        export const reviewHelpRequests = () => Promise.resolve([]);
        export const decideHelpRequest = () => Promise.resolve({reply: 'Reviewed'});
        export const getMeetings = () => Promise.resolve([]);
        export const createMeeting = () => Promise.resolve({id: 'synthetic-meeting'});
        export const saveAttendance = () => Promise.resolve();
        export const getDependencies = () => Promise.resolve([]);
        export const getTaskDraft = () => Promise.resolve(null);
        export const saveTaskDraft = form => { globalThis.__dashboard.draft = form; return Promise.resolve(form); };
        export const generateTaskPlan = body => { globalThis.__dashboard.plan = body; return Promise.resolve({tasks:[{id:'planned',title:'Planned action',rationale:'Synthetic rationale'}]}); };
        export const createTaskRecord = body => { globalThis.__dashboard.created = body; const t={...body,id:'created',status:'Upcoming',notes:'',assignee:body.owner_code}; globalThis.__dashboard.tasks.push(t); return Promise.resolve(t); };
        export const saveTaskNotes = (id, notes) => { globalThis.__dashboard.tasks = globalThis.__dashboard.tasks.map(t => t.id===id ? {...t,notes} : t); return Promise.resolve(); };
        export const editMember = () => Promise.resolve();
        export const getEvaluation = () => Promise.resolve({comments:''});
        export const saveEvaluation = () => Promise.resolve();
        export const ingestMeetingAudio = () => Promise.resolve();
      ` : args.path.includes('reassignments') ? 'export const reassignmentStore = () => ({list: () => globalThis.__dashboard.list(), review: (...a) => globalThis.__dashboard.review(...a), submit: (...a) => globalThis.__dashboard.submit(...a)});'
        : args.path.includes('supabase') ? 'export const supabase = {};'
        : 'export default function Recorder() { return null; }',
    }));
  } }],
});
const { default: App } = await import(pathToFileURL(output));
const text = node => typeof node === 'string' ? node : (node?.children ?? []).map(text).join('');
const button = (renderer, label) => renderer.root.findAllByType('button').find(b => text(b) === label);
const profile = { id: 'profile1', member_code: 'MEMBER', name: 'Member', role: 'member' };
function setup() {
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  globalThis.__dashboard = {
    tasks: [{ id: 'task1', title: 'Database task', status: 'Upcoming', ownerCode: 'MEMBER', originalAssigneeCode: 'MEMBER', due: 'No date', start: '?', day: -1, len: 1, finished: '', notes: '', assigneeText: 'Member' }],
    people: [{ id: 'MEMBER', name: 'Member', role: 'member', skills: [] }, { id: 'OTHER', name: 'Other', role: 'member', skills: [] }],
    rows: [{ id: 'request1', task_id: 'task1', requester_code: 'MEMBER', proposed_assignee_code: 'OTHER', status: 'pending', reason: 'Busy', created_at: '2026-11-14T12:00:00Z' }],
    list() { return Promise.resolve(this.rows); },
    review(_id, decision) {
      this.rows = this.rows.map(r => ({ ...r, status: decision }));
      if (decision === 'approved') this.tasks = this.tasks.map(t => ({ ...t, ownerCode: 'OTHER', assigneeText: 'Other' }));
      return Promise.resolve();
    },
    submit(taskId, code, reason) {
      this.rows = [{ id: 'request2', task_id: taskId, requester_code: 'MEMBER', proposed_assignee_code: code, reason, status: 'pending', created_at: '2026-11-14T12:00:00Z' }];
      return Promise.resolve();
    },
  };
}

test('admin decisions reload persisted queue and task assignment; failures remain visible', async () => {
  setup(); let renderer;
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(renderer, 'Requests (1)').props.onClick());
    assert.ok(button(renderer, 'Approve'));
    const goodReview = globalThis.__dashboard.review;
    globalThis.__dashboard.review = async () => { throw new Error('Task assignment changed'); };
    await act(async () => button(renderer, 'Approve').props.onClick());
    assert.ok(renderer.root.findAllByProps({ role: 'alert' }).some(n => text(n).includes('Task assignment changed')));
    assert.ok(button(renderer, 'Approve'), 'failed decisions must leave pending actions visible');
    globalThis.__dashboard.review = goodReview;
    await act(async () => button(renderer, 'Approve').props.onClick());
    assert.equal(button(renderer, 'Approve'), undefined);
    assert.ok(button(renderer, 'Requests (0)'));
    assert.equal(globalThis.__dashboard.tasks[0].ownerCode, 'OTHER');
    assert.equal(globalThis.__dashboard.tasks[0].originalAssigneeCode, 'MEMBER');
  } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
});

for (const decision of ['approved', 'rejected', 'failure']) {
  test(`admin hides a request during a delayed ${decision} decision and survives refreshes`, async () => {
    setup(); let renderer, finishReview, reviewPromise;
    const dashboard = globalThis.__dashboard;
    const goodReview = dashboard.review.bind(dashboard);
    dashboard.review = () => new Promise((resolve, reject) => {
      finishReview = () => decision === 'failure'
        ? reject(new Error('Decision failed'))
        : goodReview('request1', decision).then(resolve);
    });
    try {
      await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
      await act(async () => button(renderer, 'Requests (1)').props.onClick());
      await act(async () => { reviewPromise = button(renderer, decision === 'rejected' ? 'Deny' : 'Approve').props.onClick(); });
      assert.equal(button(renderer, 'Approve'), undefined, 'hide before the RPC resolves');
      assert.ok(button(renderer, 'Requests (0)'));
      assert.equal(renderer.root.findAllByProps({ className: 'req' }).length, 0);
      await act(async () => button(renderer, 'Refresh').props.onClick());
      assert.equal(button(renderer, 'Approve'), undefined, 'a pending server row must stay hidden during saving');
      if (decision !== 'failure') dashboard.list = async () => { throw new Error('Refresh unavailable'); };
      await act(async () => { finishReview(); await reviewPromise; });
      if (decision === 'failure') {
        assert.ok(button(renderer, 'Requests (1)'));
        assert.ok(button(renderer, 'Approve'), 'restore the request when saving fails');
        assert.ok(renderer.root.findAllByProps({ role: 'alert' }).some(n => text(n).includes('Decision failed')));
      } else {
        assert.ok(button(renderer, 'Requests (0)'));
        assert.equal(button(renderer, 'Approve'), undefined, 'a saved decision stays out of pending even if refresh fails');
        assert.ok(renderer.root.findAllByProps({ className: 'req' }).some(n => text(n).includes(decision)));
      }
    } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
  });
}

test('member requests persist and show pending without exposing approval controls', async () => {
  setup(); let renderer;
  globalThis.__dashboard.rows = [];
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: false, signOut() {} })); });
    const taskButton = renderer.root.findAllByType('button').find(b => b.props.title === 'Database task');
    await act(async () => taskButton.props.onClick());
    const choice = renderer.root.findAllByType('select').find(s => s.props.value === '');
    await act(async () => choice.props.onChange({ target: { value: 'OTHER' } }));
    await act(async () => button(renderer, 'Send request').props.onClick());
    assert.equal(globalThis.__dashboard.rows[0].proposed_assignee_code, 'OTHER');
    await act(async () => button(renderer, 'Requests (1)').props.onClick());
    assert.equal(button(renderer, 'Approve'), undefined);
    assert.equal(button(renderer, 'Deny'), undefined);
    assert.ok(renderer.root.findAllByType('h2').some(n => text(n) === 'Pending (1)'));
  } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
});

test('manual task creation sends structured dates and owner; saved board notes survive remount', async () => {
  setup(); let renderer;
  const change = async (node, value) => act(async () => node.props.onChange({ target: { value } }));
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(renderer, 'ADMIN SETTINGS').props.onClick());
    await act(async () => button(renderer, 'Create Task').props.onClick());
    await act(async () => button(renderer, 'Enter Manually').props.onClick());
    await change(renderer.root.findAllByType('input').find(n => n.props.maxLength === 200), 'Persisted task');
    const dates = () => renderer.root.findAllByType('input').filter(n => n.props.type === 'date');
    await change(dates()[0], '2026-11-16');
    await change(dates()[1], '2026-11-20');
    await change(renderer.root.findAllByType('input').find(n => n.props.type === 'time'), '18:30');
    await change(renderer.root.findAllByType('select').find(n => n.findAllByType('option').some(o => text(o) === 'Unassigned')), 'OTHER');
    await act(async () => button(renderer, 'Save Draft').props.onClick());
    assert.equal(globalThis.__dashboard.draft.ownerCode, 'OTHER');
    await act(async () => button(renderer, 'Submit').props.onClick());
    assert.deepEqual(Object.fromEntries(['title','start_date','due_date','due_time','owner_code','month_code'].map(k => [k,globalThis.__dashboard.created[k]])), {
      title:'Persisted task',start_date:'2026-11-16',due_date:'2026-11-20',due_time:'18:30',owner_code:'OTHER',month_code:'2026-11',
    });
    const note = renderer.root.findByType('textarea');
    assert.equal(note.props.value, '', 'description must not become board notes');
    await change(note, 'Saved board note');
    await act(async () => button(renderer, 'Save notes').props.onClick());
    assert.equal(globalThis.__dashboard.tasks.find(t => t.id === 'created').notes, 'Saved board note');
    await act(async () => renderer.unmount());
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => renderer.root.findAllByType('button').find(b => b.props.title === 'Persisted task').props.onClick());
    assert.equal(renderer.root.findByType('textarea').props.value, 'Saved board note');
  } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
});

test('nudge control is admin-only and never claims a reminder was sent', async () => {
  setup(); let adminRenderer, memberRenderer;
  try {
    await act(async () => { adminRenderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(adminRenderer, 'Tasks').props.onClick());
    const nudge = adminRenderer.root.findAllByType('button').find(b => b.props['aria-label'] === 'Nudge assignee for Database task');
    assert.ok(nudge);
    assert.equal(nudge.props.disabled, false);
    await act(async () => nudge.props.onClick({ stopPropagation() {} }));
    assert.ok(adminRenderer.root.findAllByProps({ role: 'status' }).some(n =>
      text(n).includes('no reminder was sent'),
    ));

    await act(async () => { memberRenderer = TestRenderer.create(React.createElement(App, { profile, admin: false, signOut() {} })); });
    await act(async () => button(memberRenderer, 'Tasks').props.onClick());
    assert.equal(memberRenderer.root.findAllByType('button').find(b => b.props['aria-label'] === 'Nudge assignee for Database task'), undefined);
  } finally {
    if (adminRenderer) await act(async () => adminRenderer.unmount());
    if (memberRenderer) await act(async () => memberRenderer.unmount());
    delete globalThis.window;
  }
});
