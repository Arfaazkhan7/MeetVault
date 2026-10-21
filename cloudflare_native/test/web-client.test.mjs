import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

test('hosted client joins raw codes and invite links without changing their identity',async()=>{
  const calls=[],started=[],messages=[];
  const noop=()=>{};
  const context={URL,TextEncoder,TextDecoder,console,location:{origin:'https://app.test',hash:''},sessionStorage:{getItem:()=>null,setItem:noop},
    document:{getElementById:()=>({value:''})},navigator:{clipboard:{writeText:async()=>{}}},window:{},
    createNewMeeting:noop,vaultSearch:noop,renderVaultMeetings:noop,initP2PCall:noop,stopStream:noop,toggleMic:noop,toggleCam:noop,shareScreen:noop,stopScreenShare:noop,endCall:async()=>{},broadcastLiveCaption:noop,doJoin:noop,copyCurrentRoomLink:noop,
    currentMeetingId:null,currentRoomCode:null,isMeetingHost:false,showToast:m=>messages.push(m),startCall:async code=>started.push(code),
    apiFetch:async(path,options)=>{calls.push({path,body:options.body?JSON.parse(options.body):null});return new Response(JSON.stringify(path==='/meetings/join'?{meeting_id:'MTG-fixture',participant:{role:'ATTENDEE'}}:{}),{status:200});}};
  vm.createContext(context);vm.runInContext(await readFile(new URL('../../web/native-client.js',import.meta.url),'utf8'),context);
  for(const value of ['abc123def456','https://app.test/index.html#/join/ABC123DEF456','MTG-OLD123'])await context.doJoin(value);
  assert.deepEqual(calls.filter(c=>c.path==='/meetings/join').map(c=>c.body.invite_code),['ABC123DEF456','ABC123DEF456','MTG-OLD123']);
  assert.deepEqual(started,['ABC123DEF456','ABC123DEF456','MTG-OLD123']);
  assert.equal(context.isMeetingHost,false);
  const before=calls.length;await context.doJoin('<script>');assert.equal(calls.length,before);assert.ok(messages.length);
});
