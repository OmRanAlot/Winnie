// Check new JSON/form-data endpoints and metrics using actual API helper functions.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { saveEvaluation, getEvaluation, saveTaskDraft, getTaskDraft,
  saveTaskNotes, ingestMeetingAudio, toUiTask } from '../src/lib/api.js';
import { memberMetrics } from '../src/lib/metrics.js';

test('editable forms use the matching backend routes and return stored responses', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok:true,json:async()=>({success:true,data:{saved:true}})};
  };
  try {
    await saveEvaluation('MEMBER','Review'); await getEvaluation('MEMBER');
    await saveTaskDraft({title:'Draft'}); await getTaskDraft();
    await saveTaskNotes('uuid-task','A note');
    assert.deepEqual(calls.map(c=>[c.options.method || 'GET',c.url]), [
      ['PUT','/api/dashboard/evaluations/MEMBER'],
      ['GET','/api/dashboard/evaluations/MEMBER'],['PUT','/api/dashboard/draft'],
      ['GET','/api/dashboard/draft'],['PATCH','/api/tasks/records/uuid-task'],
    ]);
    assert.deepEqual(JSON.parse(calls[4].options.body),{notes:'A note'});
    const audio = new File(['audio'],'meeting.wav',{type:'audio/wav'});
    await ingestMeetingAudio(audio,'Board meeting');
    assert.equal(calls[5].url,'/api/meetings/ingest');
    assert.equal(calls[5].options.headers['Content-Type'],undefined);
    assert.equal(calls[5].options.body.get('title'),'Board meeting');
  } finally { globalThis.fetch = original; }
});

test('task mapping retains meeting provenance, notes and schedule instead of fabricating values', () => {
  const task = toUiTask({id:'t',status:'done',description:'Original',notes:'Separate note',
    start_date:'2026-11-15',due_date:'2026-11-20',due_time:'18:30:00',source_meeting_id:9,
    updated_at:'2026-11-20T20:00:00Z'});
  assert.equal(task.meetingId,9); assert.equal(task.start,'11/15/2026'); assert.equal(task.dueTime,'18:30');
  assert.equal(task.description,'Original'); assert.equal(task.notes,'Separate note');
  assert.equal(task.completedAt,null); assert.equal(task.finished,'');
});

test('metrics distinguish zero, unknown completion times, and unrecorded attendance', () => {
  assert.equal(memberMetrics('A',[],[],[]).completion,null);
  const tasks = [{assignee:'A',status:'Completed',dueIso:'2026-11-20',completedAt:null},
    {assignee:'A',status:'Completed',dueIso:'2026-11-20',completedAt:'2026-11-21T02:00:00Z'},
    {assignee:'A',status:'Upcoming'}, {assignee:'OTHER',status:'Completed'}];
  const meetings = [{attendees:['A'],attendance_recorded_at:null},
    {attendees:[],attendance_recorded_at:'2026-11-20T12:00:00Z'}];
  const metric = memberMetrics('A',tasks,meetings,[{status:'approved',requester_code:'A'}]);
  assert.equal(metric.total,3); assert.equal(metric.completed,2); assert.equal(metric.completion,67);
  assert.equal(metric.onTime,100); assert.equal(metric.timedCompletions,1);
  assert.equal(metric.attendance,0); assert.equal(metric.recordedMeetings,1); assert.equal(metric.transfers,1);
});
