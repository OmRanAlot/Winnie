import assert from 'node:assert/strict';
import {test} from 'node:test';
import {deliver} from './send.mjs';
const env={WINNIE_PHOTON_PROJECT_ID:'project',WINNIE_PHOTON_PROJECT_SECRET:'private'};
test('request-scoped SDK send preserves chat, uses stable client ID, verifies acceptance, and closes',async()=>{
 const calls=[];
 const client={messages:{sendText:async(...args)=>{calls.push(args);return {guid:'receipt',isSent:true,sendErrorCode:0};}},close:async()=>calls.push('closed')};
 const result=await deliver({space_id:'opaque-chat',phone:'shared',text:'Synthetic reply',dedupe_key:'stable'},env,
  async()=>({ok:true,json:async()=>({data:{type:'shared',token:'short-lived'}})}),options=>{assert.equal(options.retry,false);return client;});
 assert.equal(result.provider_id,'receipt');assert.deepEqual(calls[0],['opaque-chat','Synthetic reply',{clientMessageId:'stable'}]);assert.equal(calls[1],'closed');
});
test('unconfirmed provider result is an error and connection still closes',async()=>{
 let closed=false;
 await assert.rejects(deliver({space_id:'chat',text:'Synthetic reply'},env,async()=>({ok:true,json:async()=>({data:{type:'shared',token:'temporary'}})}),()=>({messages:{sendText:async()=>({guid:'r',isSent:false})},close:async()=>{closed=true;}})),/not confirmed/);
 assert.ok(closed);
});
test('dedicated sends rotate across lines when phone is omitted',async()=>{
 const seen=[];
 const factory=(options)=>{
  const host=options.address.split('.')[0];
  seen.push(host);
  return {messages:{sendText:async()=>({guid:`receipt-${host}`,isSent:true,sendErrorCode:0})},close:async()=>{}};
 };
 const tokens=async()=>({ok:true,json:async()=>({data:{
  type:'dedicated',
  auth:{'line-a':'tok-a','line-b':'tok-b'},
  numbers:{'line-a':'+15551111111','line-b':'+15552222222'},
 }})});
 await deliver({space_id:'chat',text:'hello',dedupe_key:'k0'},env,tokens,factory);
 await deliver({space_id:'chat',text:'hello',dedupe_key:'k1'},env,tokens,factory);
 assert.deepEqual([...new Set(seen)].sort(),['line-a','line-b']);
});
test('dedicated sends pin to the requested line when phone is set',async()=>{
 let address='';
 await deliver({space_id:'chat',phone:'+15552222222',text:'hello',dedupe_key:'pin'},env,
  async()=>({ok:true,json:async()=>({data:{
   type:'dedicated',auth:{'line-a':'tok-a','line-b':'tok-b'},
   numbers:{'line-a':'+15551111111','line-b':'+15552222222'},
  }})}),
  options=>{address=options.address;return {messages:{sendText:async()=>({guid:'ok',isSent:true,sendErrorCode:0})},close:async()=>{}};});
 assert.equal(address,'line-b.imsg.photon.codes:443');
});
