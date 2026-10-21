import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
import {generateKeyPair,exportJWK,SignJWT,createLocalJWKSet,jwtVerify} from 'jose';
import {Db,sign,verify,firebaseClaims} from '../src/core.js';
import {handle} from '../src/index.js';
import {firebaseUser} from '../src/accounts.js';
import {filters,retrieve,askEvidence} from '../src/intelligence.js';

let pg,db;const env={JWT_SECRET:'synthetic-test-secret-that-is-at-least-32-bytes',LIVEKIT_API_KEY:'synthetic',LIVEKIT_API_SECRET:'synthetic-livekit-secret-long-enough-32',SUPABASE_SERVICE_ROLE_KEY:'synthetic',SUPABASE_URL:'https://storage.invalid',SUPABASE_STORAGE_BUCKET:'meeting-recordings',SUPABASE_DOCUMENTS_BUCKET:'meeting-documents',FIREBASE_PROJECT_ID:'test-project',BACKEND_CORS_ORIGINS:'https://app.test',FRONTEND_PUBLIC_URL:'https://app.test',AI_JOBS:{send:async()=>{}}};
const connect=async()=>new Db({query:(q,p)=>pg.query(q,p),end:async()=>{}});
const users={a:{public_id:'TEST-USER-A',email:'a@example.invalid',full_name:'Person A',account_type:'personal'},b:{public_id:'TEST-USER-B',email:'b@example.invalid',full_name:'Person B',account_type:'personal'},c:{public_id:'TEST-USER-C',email:'c@example.invalid',full_name:'Person C',account_type:'personal'}};
async function request(path,method='GET',data,user='a',extra={}){
  const headers={origin:'https://app.test',...extra};if(user)headers.authorization=`Bearer ${await sign({sub:users[user].public_id,type:'access'},env.JWT_SECRET)}`;
  if(data!==undefined)headers['content-type']='application/json';
  return handle(new Request(`https://api.test/api/v1${path}`,{method,headers,body:data===undefined?undefined:JSON.stringify(data)}),env,{}, {connect});
}
before(async()=>{
  pg=new PGlite();await pg.exec(await readFile(new URL('./schema.sql',import.meta.url),'utf8'));db=await connect();
  for(const user of Object.values(users))await db.insert('users',user);
  await db.insert('companies',{public_id:'TEST-COMPANY',name:'Test',workspace_code:'TEST-WORKSPACE'});
  await db.insert('company_members',{user_id:users.a.public_id,company_id:'TEST-COMPANY',role:'SUPER_ADMIN'});
  await db.insert('projects',{public_id:'TEST-PROJECT',company_id:'TEST-COMPANY',name:'Test Project',status:'ACTIVE'});
  await db.insert('project_members',{user_id:users.a.public_id,project_id:'TEST-PROJECT',role:'OWNER'});
  // Match the older production nullability: new code must also work there.
  for(const col of ['company_id','storage_bucket','storage_path','original_filename','file_type','file_size_bytes'])await db.rows(`ALTER TABLE meeting_recordings ALTER COLUMN ${col} SET NOT NULL`);
});
after(async()=>{await pg.close();});

test('preflight is fast and does not connect to the database',async()=>{
  const connect=()=>{throw new Error('must not connect');};
  const r=await handle(new Request('https://api.test/api/v1/auth/firebase/google',{method:'OPTIONS',headers:{origin:'https://app.test','access-control-request-headers':'authorization,content-type'}}),env,{}, {connect});
  assert.equal(r.status,204);assert.equal(r.headers.get('access-control-allow-origin'),'https://app.test');
  const denied=await handle(new Request('https://api.test/api/v1/auth/firebase/google',{method:'OPTIONS',headers:{origin:'https://attacker.test'}}),env,{}, {connect});assert.equal(denied.status,403);
});
test('refresh tokens cannot authenticate protected API routes',async()=>{
  const token=await sign({sub:users.a.public_id,type:'refresh'},env.JWT_SECRET);
  const r=await request('/auth/me','GET',undefined,null,{authorization:`Bearer ${token}`});assert.equal(r.status,401);
});
test('Firebase signature, project, expiry, verified email and auth_time are checked',async()=>{
  const {publicKey,privateKey}=await generateKeyPair('RS256'),jwk=await exportJWK(publicKey);jwk.kid='test-key';
  const keys=createLocalJWKSet({keys:[jwk]});const now=Math.floor(Date.now()/1000);
  const make=extra=>new SignJWT({sub:'firebase-test-uid',email:'firebase@example.invalid',email_verified:true,auth_time:now-1,iat:now-1,exp:now+3600,aud:'test-project',iss:'https://securetoken.google.com/test-project',...extra}).setProtectedHeader({alg:'RS256',kid:'test-key'}).sign(privateKey);
  assert.equal((await firebaseClaims(await make({}),'test-project',keys)).sub,'firebase-test-uid');
  for(const extra of [{aud:'another-project'},{email_verified:false},{exp:now-1},{auth_time:now+3600},{iat:now+3600}])await assert.rejects(firebaseClaims(await make(extra),'test-project',keys));
});
test('Firebase account reuse preserves existing identity and rejects conflicting identities',async()=>{
  const user=await firebaseUser(db,{sub:'firebase-test-a',email:users.a.email,name:'Person A'});assert.equal(user.public_id,users.a.public_id);
  assert.equal((await firebaseUser(db,{sub:'firebase-test-a',email:users.a.email})).public_id,users.a.public_id);
  await assert.rejects(firebaseUser(db,{sub:'another-uid',email:users.a.email}),e=>e.status===409);
});
let first,second;
test('meeting creation is atomic and UUID IDs do not depend on row counts',async()=>{
  const r=await request('/meetings/personal','POST',{title:'Planning'});assert.equal(r.status,201);first=await r.json();
  const r2=await request('/meetings/personal','POST',{title:'Follow-up'});assert.equal(r2.status,201);second=await r2.json();assert.notEqual(first.public_id,second.public_id);assert.notEqual(first.invite_code,second.invite_code);
  assert.equal((await db.one('SELECT count(*)::int AS n FROM meeting_participants WHERE meeting_id=$1 AND role=$2',[first.public_id,'HOST'])).n,1);
});
test('outsider cannot read or end a meeting; invite code creates an attendee, never a host',async()=>{
  assert.equal((await request(`/meetings/${first.public_id}`,'GET',undefined,'b')).status,404);
  assert.equal((await request(`/meetings/${first.public_id}/end`,'POST',{},'b')).status,404);
  const joined=await request('/meetings/join','POST',{invite_code:first.invite_code},'b');assert.equal(joined.status,200);
  const connection=await joined.json();assert.equal(connection.participant.role,'ATTENDEE');
  const {payload}=await jwtVerify(connection.token,new TextEncoder().encode(env.LIVEKIT_API_SECRET),{algorithms:['HS256']});
  assert.equal(payload.video.room,`meeting-${first.public_id}`);assert.equal(payload.video.roomJoin,true);
  assert.equal((await request(`/meetings/${first.public_id}/end`,'POST',{},'b')).status,403);
});
test('history is bounded, includes real participants, and is account-scoped',async()=>{
  const a=await (await request('/meetings/history')).json(),b=await (await request('/meetings/history','GET',undefined,'b')).json(),c=await(await request('/meetings/history','GET',undefined,'c')).json();
  assert.equal(a.length,2);assert.equal(b.length,1);assert.equal(c.length,0);assert.equal(b[0].participants.length,2);
});
test('recording start works with the migrated database constraints',async()=>{
  const r=await request(`/meetings/${first.public_id}/recordings/auto/start`,'POST',{});assert.equal(r.status,200);const data=await r.json();assert.equal(data.processing_status,'RECORDING');assert.ok(data.session_id);assert.ok(data.storage_path.startsWith(first.public_id+'/'));
  assert.equal((await request(`/meetings/${first.public_id}/recordings/auto/start`,'POST',{},'b')).status,403);
});
test('cross-meeting retrieval contains evidence only from authorized meetings',async()=>{
  await db.insert('transcript_segments',{meeting_id:first.public_id,speaker_label:'SPEAKER_0',speaker_confirmed:true,speaker_user_id:users.a.public_id,attribution_status:'confirmed',text:'The launch is postponed until Friday.',start_time:12,end_time:18});
  await db.insert('transcript_segments',{meeting_id:second.public_id,speaker_label:'SPEAKER_1',speaker_confirmed:false,attribution_status:'unknown',text:'The launch remains postponed; testing is unfinished.',start_time:6,end_time:11});
  const mine=await retrieve(db,users.a,{question:'What changed about the launch?'});assert.equal(mine.meetings.length,2);assert.equal(mine.evidence.length,2);
  const attendee=await retrieve(db,users.b,{question:'launch'});assert.equal(attendee.evidence.length,1);
  const outsider=await retrieve(db,users.c,{question:'launch'});assert.equal(outsider.evidence.length,0);
  await assert.rejects(retrieve(db,users.b,{question:'launch',meeting_ids:[second.public_id]}),e=>e.status===403);
});
test('project filters reject an outsider even when the project name is known',async()=>{
  await assert.rejects(retrieve(db,users.b,{question:'launch',project_id:'TEST-PROJECT'}),e=>e.status===403);
  const f=filters(users.a,{question:'launch',company_id:'TEST-COMPANY',meeting_ids:[first.public_id]});assert.ok(f.where.includes('m.company_id=$2'));assert.deepEqual(f.params,[users.a.public_id,'TEST-COMPANY',[first.public_id]]);
});
test('cross-meeting AI receives bounded source evidence and validates citations',async()=>{
  const r=await retrieve(db,users.a,{question:'What changed about launch?'});let input;
  const result=await askEvidence({...env,AI:{run:async(_model,payload)=>{input=payload;return {response:JSON.stringify({synthesis:'The launch stayed postponed [E1] [E2].',insufficient_evidence:false,citation_ids:['E1','E2']})};}}},r);
  assert.equal(result.insufficient_evidence,false);assert.equal(result.evidence_citations.length,2);assert.match(input.messages[0].content,/untrusted data/);
  const invalid=await askEvidence({...env,AI:{run:async()=>({response:JSON.stringify({synthesis:'Invented [E999]',insufficient_evidence:false,citation_ids:['E999']})})}},r);
  assert.equal(invalid.ai_available,false);assert.equal(invalid.model_used,'Saved evidence retrieval');
});
test('empty evidence never calls AI and quota exhaustion retains saved evidence',async()=>{
  let called=false;const empty=await askEvidence({...env,AI:{run:async()=>{called=true;}}},{question:'q',evidence:[],meetings:[]});assert.equal(called,false);assert.equal(empty.insufficient_evidence,true);
  const r=await retrieve(db,users.a,{question:'launch'});const out=await askEvidence({...env,AI:{run:async()=>{throw new Error('quota');}}},r);assert.equal(out.ai_available,false);assert.ok(out.evidence_citations.length);
});
test('signed uploads stay private, enforce ownership, and enqueue a durable job',async()=>{
  const oldFetch=globalThis.fetch;let sends=0;const oldSend=env.AI_JOBS.send;env.AI_JOBS.send=async()=>{sends++;};
  globalThis.fetch=async(url)=>{
    if(String(url).includes('/object/upload/sign/'))return Response.json({url:'/object/upload/sign/meeting-recordings/test?token=synthetic'});
    if(String(url).includes('/object/info/'))return Response.json({metadata:{size:1234,mimetype:'audio/webm'}});
    throw new Error('Unexpected external request');
  };
  try{
    const r=await request(`/meetings/${second.public_id}/recordings/upload-url`,'POST',{filename:'sample.webm',content_type:'audio/webm',size:1234,duration_seconds:5});assert.equal(r.status,200);const signed=await r.json();
    assert.equal(signed.upload_url,'https://storage.invalid/storage/v1/object/upload/sign/meeting-recordings/test?token=synthetic');
    assert.equal((await request(`/meetings/${second.public_id}/recordings/complete`,'POST',{recording_id:signed.recording_id},'b')).status,404);
    const complete=await request(`/meetings/${second.public_id}/recordings/complete`,'POST',{recording_id:signed.recording_id});assert.equal(complete.status,201);const queued=await complete.json();assert.ok(queued.ai_job_id);assert.equal(sends,1);
    const job=await db.one('SELECT * FROM ai_jobs WHERE public_id=$1',[queued.ai_job_id]);assert.equal(job.status,'QUEUED');assert.equal(job.recording_id,signed.recording_id);
  }finally{globalThis.fetch=oldFetch;env.AI_JOBS.send=oldSend;}
});
test('callback secret is required even for a known job ID',async()=>{
  env.CLOUDFLARE_AI_CALLBACK_SECRET='synthetic-worker-callback-secret';
  const job=await db.one('SELECT public_id FROM ai_jobs LIMIT 1');
  const r=await request(`/ai-jobs/${job.public_id}/cloudflare/context`,'GET',undefined,null);assert.equal(r.status,401);
});
test('analysis stores genuine source references and is idempotent',async()=>{
  const segment=await db.one('SELECT id FROM transcript_segments WHERE meeting_id=$1',[second.public_id]);const old=env.AI;
  env.AI={run:async()=>({response:JSON.stringify({summary:'Launch is postponed.',key_takeaways:['Testing remains unfinished.'],topics:[{name:'Launch'}],decisions:[{title:'Postpone launch',status:'accepted',source_id:segment.id},{title:'Invented',source_id:'not-real'}],tasks:[{title:'Complete testing',source_id:segment.id}]})})};
  try{
    assert.equal((await request(`/meetings/${second.public_id}/analyze`,'POST',{})).status,200);
    const result=await(await request(`/meetings/${second.public_id}/full-analysis`)).json();assert.equal(result.decisions.length,1);assert.equal(result.tasks.length,1);assert.equal(result.evidence.length,2);assert.equal(result.summary.summary_text,'Launch is postponed.');
    assert.equal((await(await request(`/meetings/${second.public_id}/analyze`,'POST',{})).json()).cached,true);
    assert.equal((await db.one('SELECT count(*)::int AS n FROM decisions WHERE meeting_id=$1',[second.public_id])).n,1);
  }finally{env.AI=old;}
});
test('workspace and project mutations reject non-members',async()=>{
  assert.equal((await request('/companies/TEST-COMPANY/projects','POST',{name:'Unauthorized'},'b')).status,403);
  assert.equal((await request('/projects/TEST-PROJECT','PATCH',{name:'Unauthorized'},'b')).status,403);
  assert.equal((await request('/companies/TEST-COMPANY/documents','GET',undefined,'b')).status,403);
  assert.equal((await request('/admin/stats')).status,403);
});
test('repeated leave calls do not double-count attendance and end is host-only',async()=>{
  assert.equal((await request(`/meetings/${first.public_id}/room/join`,'POST',{})).status,200);
  await db.rows("UPDATE meeting_participants SET join_time=now()-interval '10 seconds' WHERE meeting_id=$1 AND user_id=$2",[first.public_id,users.a.public_id]);
  await request(`/meetings/${first.public_id}/room/leave`,'POST',{});const p1=await db.one('SELECT attendance_duration_seconds FROM meeting_participants WHERE meeting_id=$1 AND user_id=$2',[first.public_id,users.a.public_id]);
  await request(`/meetings/${first.public_id}/room/leave`,'POST',{});const p2=await db.one('SELECT attendance_duration_seconds FROM meeting_participants WHERE meeting_id=$1 AND user_id=$2',[first.public_id,users.a.public_id]);assert.equal(p1.attendance_duration_seconds,p2.attendance_duration_seconds);assert.ok(p2.attendance_duration_seconds>=10);
  assert.equal((await request(`/meetings/${first.public_id}/end`,'POST',{})).status,200);
  assert.equal((await request('/meetings/join','POST',{invite_code:first.invite_code},'b')).status,409);
});
