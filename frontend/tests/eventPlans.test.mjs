import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createEventPlan, getEventPlan, getEventPlans, updateEventPlan, reviewEventPlan } from '../src/lib/eventPlans.js';

test('event plan reads and writes use authenticated backend storage and explicit revisions', async () => {
 const original=globalThis.fetch, calls=[];
 globalThis.fetch=async (url,options)=>{
  calls.push([url,options]);
  const row={id:'plan',revision:2,status:'draft',payload:{event_name:'Shared workshop',tasks:[]}};
  return Response.json({success:true,data:url==='/api/event-plans' && !options.method ? [row] : row});
 };
 try {
  assert.equal((await getEventPlans())[0].event_name,'Shared workshop');
  assert.equal((await getEventPlan('plan')).revision,2);
  await createEventPlan({event_name:'New workshop'});
  await updateEventPlan('plan',{event_name:'Edited'},2);
  assert.equal(calls[2][1].method,'POST');
  assert.deepEqual(JSON.parse(calls[3][1].body),{event_name:'Edited',expected_revision:2});
  assert.equal(calls[3][1].method,'PUT');
 } finally {globalThis.fetch=original;}
});

test('approval preserves a committed result if text dispatch fails; conflicts stay visible', async () => {
 const original=globalThis.fetch;
 globalThis.fetch=async (url,options)=>{
  if(url.includes('/photon/')) throw new Error('queue unavailable');
  assert.deepEqual(JSON.parse(options.body),{expected_revision:3,decision:'approved'});
  return Response.json({success:true,data:{id:'plan',status:'approved',payload:{},activated_task_ids:['task']}});
 };
 try {
  const saved=await reviewEventPlan('plan',3,'approved');
  assert.equal(saved.status,'approved'); assert.match(saved.notification_warning,/Tasks created/);
  globalThis.fetch=async()=>Response.json({detail:'Stale revision'},{status:409});
  await assert.rejects(updateEventPlan('plan',{event_name:'Stale'},2),/409.*Stale revision/);
 } finally {globalThis.fetch=original;}
});
