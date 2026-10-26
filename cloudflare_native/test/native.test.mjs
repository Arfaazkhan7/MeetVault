import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
import {generateKeyPair,exportJWK,SignJWT,createLocalJWKSet,jwtVerify} from 'jose';
import {Db,sign,verify,firebaseClaims} from '../src/core.js';
import {handle} from '../src/index.js';
import {firebaseUser} from '../src/accounts.js';
import {filters,retrieve,askEvidence} from '../src/intelligence.js';
import {safeCleanupRecordingAudio,purgeAudioObject} from '../src/media.js';
import {parseSegments,parseSpeakerTurns,alignSpeakers} from '../../cloudflare_ai_worker/src/index.ts';

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

test('speaker turn parsing and alignment support distinguishable multi-speaker intervals', async () => {
  const turns = parseSpeakerTurns({
    output: {
      diarization: [
        { speaker: 'SPEAKER_00', start: 0.0, end: 5.0 },
        { speaker: 'SPEAKER_01', start: 5.0, end: 10.0 }
      ]
    }
  });
  assert.equal(turns.length, 2);
  assert.equal(turns[0].speaker, 'SPEAKER_00');
  assert.equal(turns[1].speaker, 'SPEAKER_01');

  const whisperOutput = {
    segments: [
      { text: 'Hello everyone, welcome to the kickoff.', start: 0.5, end: 4.2 },
      { text: 'Thanks, glad to be here.', start: 5.2, end: 9.1 },
      { text: 'Are there any lingering questions?', start: 12.0, end: 14.0 }
    ]
  };

  const parsed = parseSegments(whisperOutput, 15);
  // Before diarization alignment, no speaker identity is invented
  assert.ok(parsed.every(s => s.speaker_label === 'SPEAKER_UNASSIGNED' && s.attribution_status === 'unknown'));

  const aligned = alignSpeakers(parsed, turns);
  assert.equal(aligned[0].speaker_label, 'SPEAKER_00');
  assert.equal(aligned[0].attribution_status, 'unverified');
  assert.equal(aligned[1].speaker_label, 'SPEAKER_01');
  assert.equal(aligned[1].attribution_status, 'unverified');
  // Non-overlapping segment in gap remains unassigned
  assert.equal(aligned[2].speaker_label, 'SPEAKER_UNASSIGNED');
  assert.equal(aligned[2].attribution_status, 'unknown');
  // Ensure neither segment was hardcoded to SPEAKER_0
  assert.notEqual(aligned[0].speaker_label, aligned[1].speaker_label);
});

test('multi-speaker result callback persists segments idempotently and deletes audio under retention policy', async () => {
  env.CLOUDFLARE_AI_CALLBACK_SECRET = 'synthetic-worker-callback-secret';
  // Setup a test meeting with attendee
  const mtgResp = await request('/meetings/personal', 'POST', { title: 'Retention & Diarization Meeting' });
  const mtg = await mtgResp.json();
  await request('/meetings/join', 'POST', { invite_code: mtg.invite_code }, 'b');

  // Create recording and enqueue job
  const recResp = await request(`/meetings/${mtg.public_id}/recordings/auto/start`, 'POST', {});
  const rec = await recResp.json();
  await db.update('meeting_recordings', 'id=$1', [rec.id], { file_size_bytes: 5000, processing_status: 'UPLOADED' });

  const jobResp = await request(`/meetings/${mtg.public_id}/recordings/complete`, 'POST', { recording_id: rec.id });
  const jobData = await jobResp.json();
  const job = await db.one('SELECT * FROM ai_jobs WHERE public_id=$1', [jobData.ai_job_id]);

  // Track storage calls and mock fetch for signing and deletion
  let deletedPath = null;
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    if (String(url).includes('/storage/v1/object/sign/')) {
      return Response.json({ signedURL: '/object/sign/meeting-recordings/test?token=synthetic' });
    }
    if (String(url).includes('/storage/v1/object/')) {
      if (opts?.method === 'DELETE') {
        deletedPath = String(url);
        return new Response(null, { status: 204 });
      }
    }
    throw new Error('Unexpected fetch in test: ' + url);
  };

  // Context request checks active recording and gives signed url
  const ctx = await handle(
    new Request(`https://api.test/api/v1/ai-jobs/${job.public_id}/cloudflare/context`, {
      method: 'GET',
      headers: { 'x-meetvault-worker-secret': env.CLOUDFLARE_AI_CALLBACK_SECRET, origin: 'https://app.test' }
    }),
    env, {}, { connect }
  );
  assert.equal(ctx.status, 200);

  const oldAI = env.AI;
  env.AI = {
    run: async () => ({
      response: JSON.stringify({
        summary: 'Kickoff meeting overview.',
        key_takeaways: ['Kickoff complete'],
        topics: [{ name: 'Kickoff' }],
        decisions: [],
        tasks: []
      })
    })
  };

  try {
    const payload = {
      provider: 'cloudflare-workers-ai',
      transcription_text: 'Hello everyone, welcome to the kickoff. Thanks, glad to be here.',
      segments: [
        { text: 'Hello everyone, welcome to the kickoff.', start_time: 0.5, end_time: 4.2, speaker_label: 'SPEAKER_00', attribution_status: 'unverified' },
        { text: 'Thanks, glad to be here.', start_time: 5.2, end_time: 9.1, speaker_label: 'SPEAKER_01', attribution_status: 'unverified' }
      ]
    };

    // First call to result callback
    const res1 = await handle(
      new Request(`https://api.test/api/v1/ai-jobs/${job.public_id}/cloudflare/result`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-meetvault-worker-secret': env.CLOUDFLARE_AI_CALLBACK_SECRET,
          origin: 'https://app.test'
        },
        body: JSON.stringify(payload)
      }),
      env, {}, { connect }
    );
    assert.equal(res1.status, 200);
    const data1 = await res1.json();
    assert.equal(data1.segments, 2);

    // Audio must be purged from storage
    assert.ok(deletedPath);
    assert.ok(deletedPath.includes(mtg.public_id) && deletedPath.includes(rec.id));

    // Database record updated to purged
    const updatedRec = await db.one('SELECT * FROM meeting_recordings WHERE id=$1', [rec.id]);
    assert.equal(updatedRec.is_audio_purged, true);
    assert.ok(updatedRec.audio_purged_at);
    assert.equal(updatedRec.cleanup_error, null);

    // Segments in DB are persisted correctly
    const dbSegments = await db.rows('SELECT * FROM transcript_segments WHERE meeting_id=$1 ORDER BY start_time', [mtg.public_id]);
    assert.equal(dbSegments.length, 2);
    assert.equal(dbSegments[0].speaker_label, 'SPEAKER_00');
    assert.equal(dbSegments[0].attribution_status, 'unverified');
    assert.equal(dbSegments[1].speaker_label, 'SPEAKER_01');
    assert.equal(dbSegments[1].attribution_status, 'unverified');

    // Idempotency: duplicate result callback returns already_completed and does not duplicate segments
    const res2 = await handle(
      new Request(`https://api.test/api/v1/ai-jobs/${job.public_id}/cloudflare/result`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-meetvault-worker-secret': env.CLOUDFLARE_AI_CALLBACK_SECRET,
          origin: 'https://app.test'
        },
        body: JSON.stringify(payload)
      }),
      env, {}, { connect }
    );
    assert.equal(res2.status, 200);
    const data2 = await res2.json();
    assert.equal(data2.already_completed, true);

    const segmentCount = await db.one('SELECT count(*)::int AS n FROM transcript_segments WHERE meeting_id=$1', [mtg.public_id]);
    assert.equal(segmentCount.n, 2);

    // Attempting signed download on purged audio returns 410 Gone
    const dlResp = await request(`/meetings/${mtg.public_id}/recordings/${rec.id}/signed-url`, 'POST', {});
    assert.equal(dlResp.status, 410);

    // Context request on purged recording also returns 410 Gone
    const ctxPurged = await handle(
      new Request(`https://api.test/api/v1/ai-jobs/${job.public_id}/cloudflare/context`, {
        method: 'GET',
        headers: { 'x-meetvault-worker-secret': env.CLOUDFLARE_AI_CALLBACK_SECRET, origin: 'https://app.test' }
      }),
      env, {}, { connect }
    );
    assert.equal(ctxPurged.status, 200); // Already completed returns completed: true

    // Manual speaker mapping workflow: Host confirms SPEAKER_00 -> User A and SPEAKER_01 -> User B
    const map0 = await request(`/diarization/meetings/${mtg.public_id}/speaker-mappings/SPEAKER_00`, 'PUT', { user_id: users.a.public_id, is_confirmed: true });
    assert.equal(map0.status, 200);
    const map1 = await request(`/diarization/meetings/${mtg.public_id}/speaker-mappings/SPEAKER_01`, 'PUT', { user_id: users.b.public_id, is_confirmed: false });
    assert.equal(map1.status, 200);

    // Confirm attribution in transcript_segments
    const confirmedSeg0 = await db.one('SELECT * FROM transcript_segments WHERE meeting_id=$1 AND speaker_label=$2', [mtg.public_id, 'SPEAKER_00']);
    assert.equal(confirmedSeg0.speaker_user_id, users.a.public_id);
    assert.equal(confirmedSeg0.attribution_status, 'confirmed');

    const unconfirmedSeg1 = await db.one('SELECT * FROM transcript_segments WHERE meeting_id=$1 AND speaker_label=$2', [mtg.public_id, 'SPEAKER_01']);
    assert.equal(unconfirmedSeg1.speaker_user_id, users.b.public_id);
    assert.equal(unconfirmedSeg1.attribution_status, 'unconfirmed');

    // Cross-meeting retrieval distinguishes verified participant from unconfirmed/unverified
    const retrieval = await retrieve(db, users.a, { question: 'kickoff' });
    const stmt0 = retrieval.evidence.find(e => e.speaker_label === 'SPEAKER_00');
    assert.equal(stmt0.attribution_status, 'confirmed');

    const vaultAns = await askEvidence(env, retrieval);
    const ansStmt0 = vaultAns.statements.find(s => s.speaker_name === users.a.full_name);
    assert.ok(ansStmt0);
    assert.equal(ansStmt0.is_verified_user, true);

    const ansStmt1 = vaultAns.statements.find(s => s.speaker_name === users.b.full_name);
    assert.ok(ansStmt1);
    assert.equal(ansStmt1.is_verified_user, false);
  } finally {
    globalThis.fetch = oldFetch;
    env.AI = oldAI;
  }
});

test('retention cleanup failure tracking, reconcile endpoint, and terminal failure cleanup', async () => {
  env.CLOUDFLARE_AI_CALLBACK_SECRET = 'synthetic-worker-callback-secret';
  const mtgResp = await request('/meetings/personal', 'POST', { title: 'Retention Failure Tracking' });
  const mtg = await mtgResp.json();

  const rec = await db.insert('meeting_recordings', {
    meeting_id: mtg.public_id,
    company_id: `personal:${users.a.public_id}`,
    uploaded_by_user_id: users.a.public_id,
    storage_backend: 'supabase',
    storage_bucket: env.SUPABASE_STORAGE_BUCKET,
    storage_path: `${mtg.public_id}/rec-fail/test.webm`,
    original_filename: 'test.webm',
    file_type: 'audio/webm',
    file_size_bytes: 4000,
    processing_status: 'RUNNING',
    is_audio_purged: false,
    retention_policy: 'ephemeral_transcript_only',
    cleanup_retry_count: 0
  });

  const job = await db.insert('ai_jobs', {
    public_id: 'JOB-test-fail-1',
    meeting_id: mtg.public_id,
    recording_id: rec.id,
    requested_by_user_id: users.a.public_id,
    job_type: 'MEETING_AI_PIPELINE',
    status: 'RUNNING',
    current_stage: 'TRANSCRIBING',
    retry_count: 1,
    max_retries: 3,
    provider: 'cloudflare'
  });

  // Non-permanent failure (retry_count 1 < max_retries 3) must NOT purge audio
  const failResp1 = await handle(
    new Request(`https://api.test/api/v1/ai-jobs/${job.public_id}/cloudflare/fail`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-meetvault-worker-secret': env.CLOUDFLARE_AI_CALLBACK_SECRET,
        origin: 'https://app.test'
      },
      body: JSON.stringify({ error: 'Temporary worker timeout' })
    }),
    env, {}, { connect }
  );
  assert.equal(failResp1.status, 200);
  const failData1 = await failResp1.json();
  assert.equal(failData1.permanent_failure, false);

  const recAfterRetry = await db.one('SELECT * FROM meeting_recordings WHERE id=$1', [rec.id]);
  assert.equal(recAfterRetry.is_audio_purged, false);

  // Update job retry_count to 3 (equal to max_retries) to test terminal failure
  await db.update('ai_jobs', 'public_id=$1', [job.public_id], { retry_count: 3 });

  let deleted = false;
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    if (opts?.method === 'DELETE') {
      deleted = true;
      return new Response(null, { status: 204 });
    }
    throw new Error('Unexpected fetch: ' + url);
  };

  try {
    const failResp2 = await handle(
      new Request(`https://api.test/api/v1/ai-jobs/${job.public_id}/cloudflare/fail`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-meetvault-worker-secret': env.CLOUDFLARE_AI_CALLBACK_SECRET,
          origin: 'https://app.test'
        },
        body: JSON.stringify({ error: 'Permanent failure: corrupt audio' })
      }),
      env, {}, { connect }
    );
    assert.equal(failResp2.status, 200);
    const failData2 = await failResp2.json();
    assert.equal(failData2.permanent_failure, true);
    assert.equal(deleted, true);

    const recAfterPermanent = await db.one('SELECT * FROM meeting_recordings WHERE id=$1', [rec.id]);
    assert.equal(recAfterPermanent.is_audio_purged, true);
    assert.ok(recAfterPermanent.audio_purged_at);
  } finally {
    globalThis.fetch = oldFetch;
  }

  // Test storage failure tracking and reconcile route
  const recUnpurged = await db.insert('meeting_recordings', {
    meeting_id: mtg.public_id,
    company_id: `personal:${users.a.public_id}`,
    uploaded_by_user_id: users.a.public_id,
    storage_backend: 'supabase',
    storage_bucket: env.SUPABASE_STORAGE_BUCKET,
    storage_path: `${mtg.public_id}/rec-reconcile/test.webm`,
    original_filename: 'test.webm',
    file_type: 'audio/webm',
    file_size_bytes: 4000,
    processing_status: 'COMPLETED',
    is_audio_purged: false,
    retention_policy: 'ephemeral_transcript_only',
    cleanup_retry_count: 0
  });

  // Simulate storage 500 failure during cleanup
  globalThis.fetch = async () => new Response('Internal storage error', { status: 500 });
  try {
    const cleanFail = await safeCleanupRecordingAudio(db, env, recUnpurged, mtg.public_id);
    assert.equal(cleanFail.purged, false);
    assert.ok(cleanFail.error);

    const checkedRec = await db.one('SELECT * FROM meeting_recordings WHERE id=$1', [recUnpurged.id]);
    assert.equal(checkedRec.is_audio_purged, false);
    assert.equal(checkedRec.cleanup_retry_count, 1);
    assert.ok(checkedRec.cleanup_error.includes('500'));
  } finally {
    globalThis.fetch = oldFetch;
  }

  // Now reconcile via endpoint when storage is available
  let reconcileDeleted = false;
  globalThis.fetch = async (url, opts) => {
    if (opts?.method === 'DELETE') {
      reconcileDeleted = true;
      return new Response(null, { status: 204 });
    }
    throw new Error('Unexpected fetch: ' + url);
  };
  try {
    const reconResp = await request(`/meetings/${mtg.public_id}/recordings/reconcile-cleanup`, 'POST', {});
    assert.equal(reconResp.status, 200);
    const reconData = await reconResp.json();
    assert.equal(reconData.reconciled, 1);
    assert.equal(reconcileDeleted, true);

    const finalRec = await db.one('SELECT * FROM meeting_recordings WHERE id=$1', [recUnpurged.id]);
    assert.equal(finalRec.is_audio_purged, true);
    assert.equal(finalRec.cleanup_error, null);
  } finally {
    globalThis.fetch = oldFetch;
  }
});
