/* One-time deployment validation. Not imported by the production entrypoint.
 * Uses isolated test accounts, never signs in as a real user, and logs no tokens.
 * Remove its temporary scheduled deployment after the test and clean fixtures. */
import {openDb,sign,uid,check} from '../src/core.js';
import {handle} from '../src/index.js';

export async function runCanary(env){
  const prefix='MVTEST-20261021-native-validation',ids={a:`${prefix}-A`,b:`${prefix}-B`},report={prefix,checks:[]};
  let db=await openDb(env);
  try{if(await db.one('SELECT public_id FROM users WHERE public_id=$1',[ids.a])){console.log(JSON.stringify({migration_canary:{prefix,phase:'already_started'}}));return;}await db.tx(async()=>{for(const [key,id] of Object.entries(ids))await db.insert('users',{public_id:id,email:`${prefix.toLowerCase()}-${key}@example.invalid`,full_name:'Migration test account',account_type:'personal',hashed_password:null});});}
  finally{await db.close();}
  const access=await sign({sub:ids.a,type:'access'},env.JWT_SECRET),outsider=await sign({sub:ids.b,type:'access'},env.JWT_SECRET),base=env.API_BASE_URL;
  async function call(path,method='GET',data,token=access,expected=200){
    const r=await handle(new Request(`${base}${path}`,{method,headers:{...(token?{authorization:`Bearer ${token}`}:{ }),origin:env.FRONTEND_PUBLIC_URL,...(data===undefined?{}:{'content-type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data)}),env,{});
    const payload=await r.json().catch(()=>null);report.checks.push({path,status:r.status,expected});check(r.status===expected,500,`Canary failed: ${method} ${path} (${r.status})`);return payload;
  }
  try{
    await call('/health','GET',undefined,null);
    const preflight=await handle(new Request(`${base}/auth/firebase/google`,{method:'OPTIONS',headers:{origin:env.FRONTEND_PUBLIC_URL,'access-control-request-method':'POST','access-control-request-headers':'content-type'}}),env,{});check(preflight.status===204,500,'Preflight failed');report.checks.push({path:'preflight',status:preflight.status});
    await call('/auth/firebase/google','POST',{id_token:'invalid-test-token'},null,401);
    await call('/auth/me');
    const m1=await call('/meetings/personal','POST',{title:`${prefix} Planning`},access,201),m2=await call('/meetings/personal','POST',{title:`${prefix} Follow-up`},access,201);
    report.meetings=[m1.public_id,m2.public_id];
    const history=await call('/meetings/history');check(history.length===2,500,'Canary history mismatch');
    await call(`/meetings/${m1.public_id}`,'GET',undefined,outsider,404);
    db=await openDb(env);try{await db.tx(async()=>{
      await db.insert('transcript_segments',{meeting_id:m1.public_id,speaker_label:'SPEAKER_0',speaker_confirmed:false,attribution_status:'unknown',start_time:0,end_time:5,text:'Test planning evidence: launch was proposed for Monday.'});
      await db.insert('transcript_segments',{meeting_id:m2.public_id,speaker_label:'SPEAKER_0',speaker_confirmed:false,attribution_status:'unknown',start_time:0,end_time:5,text:'Test follow-up evidence: launch was postponed until Friday for testing.'});
    });}finally{await db.close();}
    const answer=await call('/cross-meeting/query','POST',{question:'How did the launch date change?',meeting_ids:report.meetings,scope:'selected_meetings'});
    check(answer.evidence_citations?.length===2,500,'Cross-meeting citations missing');report.ai_synthesis=answer.ai_available!==false;
    await call('/cross-meeting/query','POST',{question:'launch',meeting_ids:report.meetings},outsider,403);
    const joined=await call('/meetings/join','POST',{invite_code:m1.invite_code},outsider);check(joined.participant.role==='ATTENDEE',500,'Invalid room role');
    await call(`/meetings/${m1.public_id}/end`,'POST',{},outsider,403);
    const sample=await fetch('https://huggingface.co/datasets/Narsil/asr_dummy/resolve/main/1.flac');check(sample.ok,500,'Test audio unavailable');const audio=await sample.arrayBuffer();
    const upload=await call(`/meetings/${m1.public_id}/recordings/upload-url`,'POST',{filename:'migration-test.flac',content_type:'audio/flac',size:audio.byteLength,duration_seconds:15});
    const stored=await fetch(upload.upload_url,{method:'PUT',headers:{'content-type':'audio/flac'},body:audio});check(stored.ok,500,'Signed upload failed');
    const queued=await call(`/meetings/${m1.public_id}/recordings/complete`,'POST',{recording_id:upload.recording_id},access,201);
    report.recording_id=upload.recording_id;report.job_id=queued.ai_job_id;report.phase='waiting_for_queue';
    console.log(JSON.stringify({migration_canary:report}));
  }catch(e){report.phase='failed';report.error=e.message;console.log(JSON.stringify({migration_canary:report}));throw e;}
}
