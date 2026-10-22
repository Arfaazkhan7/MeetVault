import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {PGlite} from '@electric-sql/pglite';
import {Db,sign} from '../src/core.js';
import {handle} from '../src/index.js';
import {wavDuration,translateText} from '../src/translation.js';

let pg,db,meeting,calls=0;const realFetch=globalThis.fetch;
const env={JWT_SECRET:'synthetic-translation-tests-only-long-secret',LIVEKIT_API_KEY:'synthetic',LIVEKIT_API_SECRET:'synthetic-livekit-secret-for-tests',LIVEKIT_URL:'wss://room.invalid',SUPABASE_SERVICE_ROLE_KEY:'synthetic',LIVE_TRANSLATION_ENABLED:'true',FRONTEND_PUBLIC_URL:'https://app.test',BACKEND_CORS_ORIGINS:'https://app.test',AI:{run:async(model,p)=>{calls++;return model.includes('whisper')?{text:'The launch is on Friday.'}:{translated_text:`${p.target_lang}: ${p.text}`};}}};
const connect=async()=>new Db({query:(q,p)=>pg.query(q,p),end:async()=>{}});
function audio(seconds=1,value=1000){
  const b=Buffer.alloc(44+seconds*32000);b.write('RIFF');b.writeUInt32LE(b.length-8,4);b.write('WAVE',8);b.write('fmt ',12);b.writeUInt32LE(16,16);b.writeUInt16LE(1,20);b.writeUInt16LE(1,22);b.writeUInt32LE(16000,24);b.writeUInt32LE(32000,28);b.writeUInt16LE(2,32);b.writeUInt16LE(16,34);b.write('data',36);b.writeUInt32LE(b.length-44,40);for(let i=44;i<b.length;i+=2)b.writeInt16LE(value,i);return b;
}
async function request(path,method='GET',value,user='HOST'){
  const bytes=value instanceof Uint8Array,headers={authorization:`Bearer ${await sign({sub:user,type:'access'},env.JWT_SECRET)}`,origin:'https://app.test','content-type':bytes?'audio/wav':'application/json'};
  return handle(new Request(`https://api.test/api/v1${path}`,{method,headers,body:value===undefined?undefined:bytes?value:JSON.stringify(value)}),env,{}, {connect});
}
const base=()=>`/meetings/${meeting.public_id}/translation`;
before(async()=>{
  pg=new PGlite();await pg.exec(await readFile(new URL('./schema.sql',import.meta.url),'utf8'));db=await connect();
  for(const role of ['anon','authenticated','service_role'])await pg.exec(`CREATE ROLE ${role}`);
  await pg.exec(await readFile(new URL('../../supabase/migrations/20261022065236_organization_translation.sql',import.meta.url),'utf8'));
  for(const id of ['HOST','ATTENDEE','OUTSIDER'])await db.insert('users',{public_id:id,email:`${id.toLowerCase()}@example.invalid`,full_name:id,account_type:'personal'});
  meeting=await(await request('/meetings/personal','POST',{title:'Translation test'})).json();
  await request(`/meetings/${meeting.public_id}/room/join`,'POST',{});
  await request('/meetings/join','POST',{invite_code:meeting.invite_code},'ATTENDEE');await request(`/meetings/${meeting.public_id}/room/join`,'POST',{},'ATTENDEE');
  globalThis.fetch=async(url,options)=>{assert.ok(String(url).startsWith('https://room.invalid/twirp/'));const payload=JSON.parse(options.body);assert.equal(payload.topic,'meetvault.translation.v1');assert.equal(payload.kind,'RELIABLE');return Response.json({});};
});
after(async()=>{globalThis.fetch=realFetch;await pg.close();});

test('only host enables translation; outsiders cannot read its state',async()=>{
  assert.equal((await request(base(),'POST',{enabled:true,save_transcripts:true},'ATTENDEE')).status,403);
  assert.equal((await request(base(),'GET',undefined,'OUTSIDER')).status,404);
  assert.equal((await request(base(),'POST',{enabled:true,save_transcripts:true})).status,200);
  const state=await(await request(base())).json();assert.equal(state.enabled,true);assert.equal(state.spoken_service_available,false);assert.equal(state.voice_preservation,false);
});
test('only joined, consenting speakers can submit bounded, valid microphone audio',async()=>{
  assert.equal((await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',audio())).status,403);
  assert.equal((await request(base()+'/preferences','PUT',{source_language:'fr',target_language:'en',share_audio:true})).status,422);
  assert.equal((await request(base()+'/preferences','PUT',{source_language:'en',target_language:'ta',share_audio:true})).status,200);
  const bad=audio();bad.writeUInt32LE(48000,24);const before=calls;
  assert.equal((await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',bad)).status,415);assert.equal(calls,before);
  assert.equal(wavDuration(audio(2)),2);assert.throws(()=>wavDuration(audio(9)));
});
test('shared inference transcribes once and translates once per unique target language',async()=>{
  await request(base()+'/preferences','PUT',{source_language:'hi',target_language:'hi',share_audio:false},'ATTENDEE');
  const before=calls,id=crypto.randomUUID(),route=base()+'/audio?segment_id='+id;
  const response=await request(route,'POST',audio());assert.equal(response.status,201);const row=await response.json();
  assert.equal(calls-before,3);assert.equal(row.translations.ta,'ta: The launch is on Friday.');assert.equal(row.translations.hi,'hi: The launch is on Friday.');
  const duplicate=await request(route,'POST',audio());assert.equal(duplicate.status,200);assert.equal(calls-before,3);
  assert.equal((await request(route,'POST',audio(1,2000))).status,409);
  const saved=await db.one("SELECT text,attribution_status,processing_metadata FROM transcript_segments WHERE segment_id=$1",['live-translation:'+row.id]);
  assert.equal(saved.text,'The launch is on Friday.');assert.equal(saved.attribution_status,'self_reported');assert.equal(saved.processing_metadata.source_language,'en');
});
test('workspace allowance rejects audio beyond the shared reservation budget',async()=>{
  env.TRANSLATION_MEETING_AUDIO_SECONDS='8';const before=calls;
  const responses=[await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',audio(4)),await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',audio(4))];
  assert.deepEqual(responses.map(r=>r.status).sort(),[201,429]);assert.equal(calls-before,3);delete env.TRANSLATION_MEETING_AUDIO_SECONDS;
});
test('consent withdrawn while inference runs prevents transcript persistence',async()=>{
  const original=env.AI,previous=await db.one('SELECT count(*)::int AS n FROM transcript_segments');
  env.AI={run:async(model)=>{await db.rows("UPDATE meeting_translation_preferences SET share_audio=false WHERE meeting_id=$1 AND user_id='HOST'",[meeting.public_id]);return model.includes('whisper')?{text:'Do not save this.'}:{translated_text:'test'};}};
  const response=await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',audio());assert.equal(response.status,409);
  assert.equal((await db.one('SELECT count(*)::int AS n FROM transcript_segments')).n,previous.n);env.AI=original;
});
test('caption-only mode keeps originals out of Vault and missing speech service is explicit',async()=>{
  await request(base(),'POST',{enabled:true,save_transcripts:false});await request(base()+'/preferences','PUT',{source_language:'en',target_language:'en',share_audio:true});
  const previous=await db.one('SELECT count(*)::int AS n FROM transcript_segments');const response=await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',audio());assert.equal(response.status,201);const row=await response.json();
  assert.equal((await db.one('SELECT count(*)::int AS n FROM transcript_segments')).n,previous.n);
  assert.equal((await request(base()+`/segments/${row.id}/speech/ta`)).status,503);
  await request(base(),'POST',{enabled:false,save_transcripts:false});assert.equal((await request(base()+'/audio?segment_id='+crypto.randomUUID(),'POST',audio())).status,409);
});
test('same-language captions reuse original text without inference',async()=>{const before=calls;assert.equal(await translateText(env,'hello','en','en'),'hello');assert.equal(calls,before);});
test('new translation tables deny direct browser roles',async()=>{
  const rows=await db.rows("SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'meeting_translation_%'");assert.equal(rows.length,3);assert.ok(rows.every(r=>r.rowsecurity));
  await pg.exec('SET ROLE anon');await assert.rejects(pg.query('SELECT * FROM meeting_translation_segments'));await pg.exec('RESET ROLE');
});
test('capture worklet downsamples to 16 kHz and outputs silent playback',async()=>{
  let Processor;const messages=[];const scope={sampleRate:48000,Int16Array,Math,AudioWorkletProcessor:class{constructor(){this.port={postMessage:b=>messages.push(new Int16Array(b))};}},registerProcessor:(_name,p)=>{Processor=p;}};
  vm.createContext(scope);vm.runInContext(await readFile(new URL('../../web/translation-capture.js',import.meta.url),'utf8'),scope);
  const p=new Processor();for(let i=0;i<188;i++)p.process([[new Float32Array(128).fill(0.25)]]);
  assert.equal(messages.length,1);assert.equal(messages[0].length,8000);assert.ok(messages[0].every(v=>v===8192));
});
