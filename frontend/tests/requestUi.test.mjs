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
    build.onResolve({ filter: /^\.\/lib\/(api\.js|supabase|reassignments\.js)$/ }, args => ({ path: args.path, namespace: 'fake' }));
    build.onResolve({ filter: /^\.\/Recorder\.jsx$/ }, args => ({ path: args.path, namespace: 'fake' }));
    build.onLoad({ filter: /.*/, namespace: 'fake' }, args => ({ contents:
      args.path.includes('api.js') ? `
        export const getTasks = () => Promise.resolve(globalThis.__dashboard.tasks);
        export const getMembers = () => Promise.resolve(globalThis.__dashboard.people);
        export const getAssignments = () => Promise.resolve({byTask: {task1: [globalThis.__dashboard.tasks[0].ownerCode]}});
        export const weekStart = () => new Date('2026-11-09T00:00:00');
        export const getCandidates = () => Promise.resolve([]);
        export const updateTaskStatus = () => Promise.resolve();
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
