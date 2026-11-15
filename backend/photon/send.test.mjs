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
