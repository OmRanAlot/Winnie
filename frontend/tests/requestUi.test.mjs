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
    build.onResolve({ filter: /^\.\/lib\/(api\.js|eventPlans\.js|supabase(?:\.js)?|reassignments\.js)$/ }, args => ({ path: args.path, namespace: 'fake' }));
    build.onResolve({ filter: /^\.\/(Recorder|SheetSync|FairyLights(?: \(1\))?)\.jsx$/ }, args => ({ path: args.path, namespace: 'fake' }));
    build.onLoad({ filter: /.*/, namespace: 'fake' }, args => ({ contents:
      args.path.includes('eventPlans.js') ? `
        export const getEventPlans = () => Promise.resolve(globalThis.__dashboard.eventPlans);
        export const getEventPlan = id => Promise.resolve(globalThis.__dashboard.eventPlans.find(plan => plan.id === id));
        export const createEventPlan = plan => { const saved={...plan,id:'event1',created_at:'2026-11-14T12:00:00Z'}; globalThis.__dashboard.eventPlans.unshift(saved); return Promise.resolve(saved); };
        export const updateEventPlan = (id, plan) => { const saved={...globalThis.__dashboard.eventPlans.find(item => item.id === id),...plan}; globalThis.__dashboard.eventPlans=globalThis.__dashboard.eventPlans.map(item => item.id===id ? saved : item); return Promise.resolve(saved); };
      ` : args.path.includes('api.js') ? `
        export const getTasks = () => Promise.resolve(globalThis.__dashboard.tasks);
        export const getMembers = () => Promise.resolve(globalThis.__dashboard.people);
        export const getAssignments = () => Promise.resolve({byTask: globalThis.__dashboard.assignments || {task1: [globalThis.__dashboard.tasks[0].ownerCode]}});
        export const weekStart = () => new Date('2026-11-09T00:00:00');
        export const getCandidates = () => Promise.resolve([]);
        export const getEventLabels = () => Promise.resolve({});
        export const updateTaskStatus = (id,status) => {
          if (globalThis.__dashboard.updateStatus) return globalThis.__dashboard.updateStatus(id,status);
          const saved={...globalThis.__dashboard.tasks.find(t=>t.id===id),status};
          globalThis.__dashboard.tasks=globalThis.__dashboard.tasks.map(t=>t.id===id?saved:t);
          return Promise.resolve(saved);
        };
        export const reviewHelpRequests = () => Promise.resolve([]);
        export const decideHelpRequest = () => Promise.resolve({reply: 'Reviewed'});
        export const getMeetings = () => Promise.resolve([]);
        export const createMeeting = () => Promise.resolve({id: 'synthetic-meeting'});
        export const saveAttendance = () => Promise.resolve();
        export const getDependencies = () => globalThis.__dashboard.dependencies ? globalThis.__dashboard.dependencies() : Promise.resolve([]);
        export const dispatchPhotonNotifications = () => Promise.resolve({queued:true});
        export const getTaskDraft = () => Promise.resolve(null);
        export const saveTaskDraft = form => { globalThis.__dashboard.draft = form; return Promise.resolve(form); };
        export const generateTaskPlan = body => { globalThis.__dashboard.plan = body; return globalThis.__dashboard.planResponse ?? Promise.resolve({
          mode:'deepagents', questions:['Confirm room capacity.'], warnings:['Review suggested dates.'],
          tasks:[
            {id:'planned',title:'Planned action',suggested_role:'Industry Partnerships Chair',kind:'highlander_hub',due_date:'2026-11-25',phase:'before',dependency_ids:[],evidence_ids:['source-1'],rationale:'Post event details.'},
            {id:'materials',title:'Prepare materials',suggested_role:'Treasurer',kind:'materials_list',due_date:'2026-11-26',phase:'before',dependency_ids:['planned'],evidence_ids:[],rationale:'Collect supplies before the event.'},
          ],
        }); };
        export const createTaskRecord = body => { globalThis.__dashboard.created = body; const t={...body,id:'created',status:'Upcoming',notes:'',assignee:body.owner_code}; globalThis.__dashboard.tasks.push(t); return Promise.resolve(t); };
        export const saveTaskNotes = (id, notes) => { globalThis.__dashboard.tasks = globalThis.__dashboard.tasks.map(t => t.id===id ? {...t,notes} : t); return Promise.resolve(); };
        export const editMember = () => Promise.resolve();
        export const getEvaluation = () => Promise.resolve({comments:''});
        export const saveEvaluation = () => Promise.resolve();
        export const ingestMeetingAudio = () => Promise.resolve();
      ` : args.path.includes('reassignments') ? 'export const reassignmentStore = () => ({list: () => globalThis.__dashboard.list(), review: (...a) => globalThis.__dashboard.review(...a), respond: (...a) => globalThis.__dashboard.respond(...a), submit: (...a) => globalThis.__dashboard.submit(...a)});'
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
  globalThis.window = {
    addEventListener() {}, removeEventListener() {},
    matchMedia() { return { matches: true, addEventListener() {}, removeEventListener() {} }; },
  };
  globalThis.__dashboard = {
    tasks: [{ id: 'task1', title: 'Database task', status: 'Upcoming', ownerCode: 'MEMBER', originalAssigneeCode: 'MEMBER', due: 'No date', start: '?', day: -1, len: 1, finished: '', notes: '', assigneeText: 'Member' }],
    people: [{ id: 'MEMBER', name: 'Member', role: 'member', skills: [] }, { id: 'OTHER', name: 'Other', role: 'member', skills: [] }],
    eventPlans: [],
    rows: [{ id: 'request1', task_id: 'task1', requester_code: 'MEMBER', proposed_assignee_code: 'OTHER', status: 'pending', reason: 'Busy', created_at: '2026-11-14T12:00:00Z' }],
    list() { return Promise.resolve(this.rows); },
    respond(id, decision) {
      this.rows = this.rows.map(r => r.id === id ? { ...r, recipient_decision: decision, status: decision === 'denied' ? 'declined' : 'pending' } : r);
      return Promise.resolve();
    },
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
  globalThis.__dashboard.rows[0].recipient_decision = 'accepted';
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

test('manual event plans save and reopen without creating tasks', async () => {
  setup(); let renderer;
  const change = async (node, value) => act(async () => node.props.onChange({ target: { value } }));
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(renderer, 'ADMIN SETTINGS').props.onClick());
    await act(async () => button(renderer, 'Plan Event').props.onClick());
    assert.equal(renderer.root.findAllByType('input').filter(node => node.props.type === 'date').length, 1);
    assert.ok(!text(renderer.toJSON()).includes('Start Date'));
    assert.ok(!text(renderer.toJSON()).includes('Due Date'));
    await change(renderer.root.findAllByType('input').find(node => node.props.maxLength === 200), 'Winnie Workshop');
    await change(renderer.root.findAllByType('textarea').find(node => node.props.maxLength === 6000), 'A hands-on event for new members.');
    await change(renderer.root.findAllByType('input').find(node => node.props.type === 'date'), '2026-11-20');
    await change(renderer.root.findAllByType('input').find(node => node.props.type === 'time'), '18:30');
    await act(async () => button(renderer, 'Enter Manually').props.onClick());
    assert.equal(renderer.root.findAllByType('input').filter(node => node.props.type === 'date').length, 1);
    await change(renderer.root.findAllByType('textarea').find(node => node.props.maxLength === 20000), 'Confirm room booking and prepare supplies.');
    await act(async () => button(renderer, 'Save Event Plan').props.onClick());
    assert.equal(globalThis.__dashboard.eventPlans[0].event_name, 'Winnie Workshop');
    assert.equal(globalThis.__dashboard.eventPlans[0].event_date, '2026-11-20');
    assert.equal(globalThis.__dashboard.eventPlans[0].event_time, '18:30');
    assert.equal(globalThis.__dashboard.eventPlans[0].plan_text, 'Confirm room booking and prepare supplies.');
    assert.equal(globalThis.__dashboard.created, undefined, 'saving an event plan must not create a task');
    await act(async () => button(renderer, 'Open').props.onClick());
    assert.equal(renderer.root.findAllByType('input').find(node => node.props.type === 'date').props.value, '2026-11-20');
    assert.equal(renderer.root.findAllByType('textarea').find(node => node.props.maxLength === 20000).props.value, 'Confirm room booking and prepare supplies.');
    await change(renderer.root.findAllByType('textarea').find(node => node.props.maxLength === 20000), 'Room is booked; supplies are ready.');
    await act(async () => button(renderer, 'Update Event Plan').props.onClick());
    assert.equal(globalThis.__dashboard.eventPlans[0].plan_text, 'Room is booked; supplies are ready.');
  } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
});

test('generated event plans receive one date and time and save as plans, not tasks', async () => {
  setup();
  globalThis.__dashboard.people = [
    { id: 'MEMBER', name: 'Carlin Verano', role: 'Industry Partnership Chair', skills: [] },
    { id: 'OTHER', name: 'Meera James', role: 'Industry Partnership Chair', skills: [] },
  ];
  let renderer;
  const change = async (node, value) => act(async () => node.props.onChange({ target: { value } }));
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(renderer, 'ADMIN SETTINGS').props.onClick());
    await act(async () => button(renderer, 'Plan Event').props.onClick());
    await change(renderer.root.findAllByType('input').find(node => node.props.maxLength === 200), 'Career Panel');
    await change(renderer.root.findAllByType('textarea').find(node => node.props.maxLength === 6000), 'Invite alumni for a career discussion.');
    await change(renderer.root.findAllByType('input').find(node => node.props.type === 'date'), '2026-12-03');
    await change(renderer.root.findAllByType('input').find(node => node.props.type === 'time'), '17:00');
    let finishPlan, generation;
    globalThis.__dashboard.planResponse = new Promise(resolve => { finishPlan = resolve; });
    await act(async () => { generation = button(renderer, 'Generate Event Plan').props.onClick(); });
    assert.ok(renderer.root.findAllByProps({ role: 'status' }).some(n => text(n).includes('Winnie is shaping')));
    assert.equal(button(renderer, 'Enter Manually').props.disabled, true);
    await act(async () => {
      finishPlan({
        mode: 'deepagents', questions: ['Confirm room capacity.'], warnings: ['Review suggested dates.'],
        tasks: [
          { id: 'planned', title: 'Planned action', suggested_role: 'Industry Partnerships Chair', kind: 'highlander_hub', due_date: '2026-11-25', phase: 'before', dependency_ids: [], evidence_ids: ['source-1'], rationale: 'Post event details.' },
          { id: 'materials', title: 'Prepare materials', suggested_role: 'Treasurer', kind: 'materials_list', due_date: '2026-11-26', phase: 'before', dependency_ids: ['planned'], evidence_ids: [], rationale: 'Collect supplies before the event.' },
        ],
      });
      await generation;
    });
    assert.equal(renderer.root.findAllByProps({ className: 'plan-loading' }).length, 0);
    assert.equal(globalThis.__dashboard.plan.event_date, '2026-12-03');
    assert.ok(globalThis.__dashboard.plan.idea.includes('Requested time: 17:00'));
    assert.equal(renderer.root.findAllByType('input').filter(node => node.props.type === 'date').length, 1);
    const taskCards = renderer.root.findAllByProps({ className: 'event-plan-task-toggle' });
    assert.equal(taskCards.length, 2);
    const firstTaskMeta = renderer.root.findAllByProps({ className: 'event-plan-task-meta' })[0];
    assert.ok(text(firstTaskMeta).includes('Industry Partnership Chair: Carlin Verano, Meera James'));
    assert.ok(!text(firstTaskMeta).includes('before'));
    assert.ok(!renderer.root.findAllByType('textarea').some(node => node.props.maxLength === 20000));
    await act(async () => taskCards[0].props.onClick());
    assert.equal(renderer.root.findAllByProps({ className: 'event-plan-task-toggle' })[0].props['aria-expanded'], true);
    assert.ok(text(renderer.toJSON()).includes('Post event details.'));
    assert.ok(text(renderer.toJSON()).includes('source-1'));
    assert.ok(text(renderer.toJSON()).includes('Confirm room capacity.'));
    await act(async () => renderer.root.findAllByProps({ className: 'event-plan-task-toggle' })[1].props.onClick());
    const expandedDetails = renderer.root.findAllByProps({ className: 'event-plan-task-details' })[0];
    assert.ok(text(expandedDetails).includes('Planned action'));
    assert.ok(!text(expandedDetails).includes('Phase'));
    await act(async () => button(renderer, 'Save Event Plan').props.onClick());
    assert.equal(globalThis.__dashboard.eventPlans[0].event_name, 'Career Panel');
    assert.equal(globalThis.__dashboard.eventPlans[0].tasks.length, 2);
    assert.equal(globalThis.__dashboard.created, undefined);
    await act(async () => button(renderer, 'Open').props.onClick());
    assert.equal(renderer.root.findAllByProps({ className: 'event-plan-task-toggle' }).length, 2);
  } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
});

test('linked-task arrows appear for admin and member Gantt views', async () => {
  for (const admin of [true, false]) {
    setup();
    globalThis.__dashboard.tasks = [
      { id: 'dependent', title: 'Dependent task', status: 'Upcoming', ownerCode: 'MEMBER', dueIso: '2026-11-14', startIso: '2026-11-13', due: '11/14/2026', start: '11/13/2026', finished: '' },
      { id: 'prerequisite', title: 'Prerequisite task', status: 'Upcoming', ownerCode: 'OTHER', dueIso: '2026-11-12', startIso: '2026-11-10', due: '11/12/2026', start: '11/10/2026', finished: '' },
    ];
    globalThis.__dashboard.dependencies = [{ task_id: 'dependent', depends_on_id: 'prerequisite' }];
    let renderer;
    try {
      await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin, signOut() {} })); });
      assert.equal(renderer.root.findAllByProps({ className: 'dependency-lines' }).length, 0);
      const linkedTasksToggle = renderer.root.findAllByType('button').find(node => text(node).includes('Show linked tasks'));
      assert.ok(linkedTasksToggle, 'the linked-task toggle is visible');
      await act(async () => linkedTasksToggle.props.onClick());
      const svg = renderer.root.findByProps({ className: 'dependency-lines' });
      const dependencyPath = svg.findAll(node => node.type === 'path' && node.props.markerEnd);
      assert.equal(dependencyPath.length, 1);
      assert.equal(dependencyPath[0].props.markerEnd, 'url(#gantt-dependency-arrowhead)');
      assert.ok(text(svg).includes('Dependent task depends on Prerequisite task'));
      assert.equal(renderer.root.findAllByProps({ className: 'gr' }).length, 2);
    } finally {
      if (renderer) await act(async () => renderer.unmount());
      delete globalThis.window;
    }
  }
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

test('incoming recipient can accept or deny; failed responses stay actionable and saved responses survive reload', async () => {
  for (const decision of ['accepted','denied']) {
    setup(); let renderer;
    const recipient = { ...profile, id:'other-profile', member_code:'OTHER', name:'Other' };
    try {
      await act(async () => { renderer = TestRenderer.create(React.createElement(App,{profile:recipient,admin:false,signOut(){}})); });
      await act(async () => button(renderer,'Requests (1)').props.onClick());
      assert.ok(button(renderer,'Accept')); assert.ok(button(renderer,'Deny'));
      assert.equal(button(renderer,'Approve'),undefined);
      const respond = globalThis.__dashboard.respond;
      globalThis.__dashboard.respond = async () => { throw new Error('Storage unavailable'); };
      await act(async () => button(renderer,decision==='accepted'?'Accept':'Deny').props.onClick());
      assert.ok(renderer.root.findAllByProps({role:'alert'}).some(n => text(n).includes('Storage unavailable')));
      assert.ok(button(renderer,'Accept'));
      globalThis.__dashboard.respond = respond;
      await act(async () => button(renderer,decision==='accepted'?'Accept':'Deny').props.onClick());
      assert.equal(globalThis.__dashboard.tasks[0].ownerCode,'MEMBER','a recipient response alone must not transfer the task');
      assert.equal(globalThis.__dashboard.rows[0].recipient_decision,decision);
      assert.equal(button(renderer,'Accept'),undefined); assert.equal(button(renderer,'Deny'),undefined);
      await act(async () => renderer.unmount());
      await act(async () => { renderer = TestRenderer.create(React.createElement(App,{profile:recipient,admin:false,signOut(){}})); });
      await act(async () => button(renderer,decision==='accepted'?'Requests (1)':'Requests (0)').props.onClick());
      assert.equal(button(renderer,'Accept'),undefined);
      assert.ok(text(renderer.toJSON()).includes(decision==='accepted'?'awaiting administrator approval':'Recipient denied'));
    } finally { if (renderer) await act(async () => renderer.unmount()); delete globalThis.window; }
  }
});

test('requester cannot answer for recipient; administrator cannot approve unanswered requests',async()=>{
  setup(); let renderer;
  try {
    await act(async () => {renderer=TestRenderer.create(React.createElement(App,{profile,admin:true,signOut(){}}));});
    await act(async () => button(renderer,'Requests (1)').props.onClick());
    assert.equal(button(renderer,'Accept'),undefined); assert.equal(button(renderer,'Deny'),undefined);
    assert.equal(button(renderer,'Approve').props.disabled,true);
    assert.equal(button(renderer,'Reject request').props.disabled,false);
  } finally {if(renderer) await act(async()=>renderer.unmount()); delete globalThis.window;}
});

test('task refresh survives secondary outages and admin Gantt defaults to all board members',async()=>{
  setup(); let renderer;
  const scheduled = {...globalThis.__dashboard.tasks[0],dueIso:'2026-11-12',due:'11/12/2026',start:'11/12/2026'};
  globalThis.__dashboard.tasks = [scheduled,{...scheduled,id:'task2',title:'Other member task',ownerCode:'OTHER'}];
  globalThis.__dashboard.list = async()=>{throw new Error('Request history offline');};
  globalThis.__dashboard.dependencies = async()=>{throw new Error('Links offline');};
  try {
    await act(async()=>{renderer=TestRenderer.create(React.createElement(App,{profile,admin:true,signOut(){}}));});
    const rows=()=>renderer.root.findAll(n=>n.props.className==='gr');
    assert.equal(rows().length,2,'secondary errors must not hide fresh tasks');
    assert.ok(rows().some(n=>text(n).includes('Other member task')));
    assert.ok(text(renderer.toJSON()).includes('Request history offline'));
    assert.ok(text(renderer.toJSON()).includes('Tasks refreshed at'));
    globalThis.__dashboard.tasks[1] = {...globalThis.__dashboard.tasks[1],title:'Updated other task',status:'Completed'};
    await act(async()=>button(renderer,'Refresh tasks').props.onClick());
    assert.ok(rows().some(n=>text(n).includes('Updated other task')));
    const filter=renderer.root.findAllByType('button').find(b=>b.props['aria-label']?.startsWith('Gantt view:'));
    await act(async()=>filter.props.onClick());
    assert.equal(rows().length,1,'My tasks still restricts the chart to the signed-in member');
    assert.ok(!rows().some(n=>text(n).includes('Updated other task')));
  } finally {if(renderer) await act(async()=>renderer.unmount()); delete globalThis.window;}
});

test('members still see only their assigned Gantt rows after default admin view changes',async()=>{
  setup(); let renderer;
  const scheduled={...globalThis.__dashboard.tasks[0],dueIso:'2026-11-12',due:'11/12/2026',start:'11/12/2026'};
  globalThis.__dashboard.tasks=[scheduled,{...scheduled,id:'foreign',title:'Other member task',ownerCode:'OTHER'}];
  try {
    await act(async()=>{renderer=TestRenderer.create(React.createElement(App,{profile,admin:false,signOut(){}}));});
    const rows=renderer.root.findAll(n=>n.props.className==='gr');
    assert.equal(rows.length,1); assert.ok(!text(rows[0]).includes('Other member task'));
  } finally {if(renderer) await act(async()=>renderer.unmount()); delete globalThis.window;}
});

test('own completed imported task renders in My tasks through its verified alias assignment',async()=>{
  setup(); let renderer;
  globalThis.__dashboard.tasks=[{...globalThis.__dashboard.tasks[0],ownerCode:null,assignee:null,
    status:'Completed',title:'Imported completed task',dueIso:'2026-11-11',due:'11/11/2026',start:'11/11/2026'}];
  globalThis.__dashboard.assignments={task1:['MEMBER']};
  try {
    await act(async()=>{renderer=TestRenderer.create(React.createElement(App,{profile,admin:true,signOut(){}}));});
    const toggle=renderer.root.findAllByType('button').find(b=>b.props['aria-label']?.startsWith('Gantt view:'));
    await act(async()=>toggle.props.onClick());
    const rows=renderer.root.findAll(n=>n.props.className==='gr');
    assert.equal(rows.length,1); assert.ok(text(rows[0]).includes('Imported completed task'));
    assert.ok(rows[0].findAll(n=>n.props.className?.includes('bar') && n.props.style?.background==='#7a2c22').length);
  } finally {if(renderer) await act(async()=>renderer.unmount()); delete globalThis.window;}
});

test('Due Soon completion shows Saving, commits once, and persists after reload',async()=>{
  setup(); let renderer, release;
  globalThis.__dashboard.tasks[0].status='In-Progress';
  let writes=0;
  globalThis.__dashboard.updateStatus=async(id,status)=>{
    writes++; await new Promise(resolve=>{release=resolve;});
    const saved={...globalThis.__dashboard.tasks[0],status}; globalThis.__dashboard.tasks=[saved]; return saved;
  };
  try {
    await act(async()=>{renderer=TestRenderer.create(React.createElement(App,{profile,admin:false,signOut(){}}));});
    let pending;
    const toggle=()=>renderer.root.findAllByType('button').find(b=>b.props['aria-label']==='Mark Database task completed');
    await act(async()=>{pending=toggle().props.onClick();});
    assert.equal(text(toggle()),'Saving…'); assert.equal(toggle().props.disabled,true);
    await act(async()=>{toggle().props.onClick();}); assert.equal(writes,1,'duplicate saves must be blocked');
    await act(async()=>{release(); await pending;});
    assert.equal(toggle(),undefined,'completed tasks leave Due Soon');
    assert.ok(text(renderer.toJSON()).includes('marked Completed and moved out of Due Soon'));
    assert.equal(globalThis.__dashboard.tasks[0].status,'Completed');
    await act(async()=>renderer.unmount());
    await act(async()=>{renderer=TestRenderer.create(React.createElement(App,{profile,admin:false,signOut(){}}));});
    assert.equal(toggle(),undefined,'reload reads the persisted completed status');
  } finally {if(renderer) await act(async()=>renderer.unmount()); delete globalThis.window;}
});

test('Due Soon failures keep the original status and a persistent actionable error',async()=>{
  setup(); let renderer;
  globalThis.__dashboard.tasks[0].status='In-Progress';
  globalThis.__dashboard.updateStatus=async()=>{throw new Error('Task storage unavailable');};
  try {
    await act(async()=>{renderer=TestRenderer.create(React.createElement(App,{profile,admin:false,signOut(){}}));});
    const toggle=()=>renderer.root.findAllByType('button').find(b=>b.props['aria-label']==='Mark Database task completed');
    await act(async()=>toggle().props.onClick());
    assert.equal(text(toggle()),'In progress'); assert.equal(toggle().props.disabled,false);
    assert.equal(globalThis.__dashboard.tasks[0].status,'In-Progress');
    assert.ok(renderer.root.findAllByProps({role:'alert'}).some(n=>text(n).includes('Task storage unavailable')));
    assert.ok(button(renderer,'Dismiss'));
  } finally {if(renderer) await act(async()=>renderer.unmount()); delete globalThis.window;}
});

test('completed tasks do not show an admin nudge control', async () => {
  setup();
  globalThis.__dashboard.tasks[0].status = 'Completed';
  let renderer;
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(renderer, 'Tasks').props.onClick());
    assert.equal(renderer.root.findAllByType('button').find(
      b => b.props['aria-label'] === 'Nudge assignee for Database task',
    ), undefined);
  } finally {
    if (renderer) await act(async () => renderer.unmount());
    delete globalThis.window;
  }
});

test('metrics overview places member names below the chart x-axis', async () => {
  setup();
  let renderer;
  try {
    await act(async () => { renderer = TestRenderer.create(React.createElement(App, { profile, admin: true, signOut() {} })); });
    await act(async () => button(renderer, 'ADMIN SETTINGS').props.onClick());
    await act(async () => button(renderer, 'Metrics Overview').props.onClick());

    const chart = renderer.root.findAllByType('svg').find(node => node.props.className === 'task-metrics-chart');
    const axisY = Math.max(...chart.findAllByType('line').map(line => Number(line.props.y1)));
    const labels = chart.findAllByType('text').filter(label => label.props.transform?.startsWith('rotate(-45'));
    assert.ok(labels.length > 0);
    assert.ok(labels.every(label => Number(label.props.y) >= axisY + 45));
  } finally {
    if (renderer) await act(async () => renderer.unmount());
    delete globalThis.window;
  }
});
