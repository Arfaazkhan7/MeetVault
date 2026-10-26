import {check,text,body,json,uid,now,publicId,meetingAccess,membership,projectAccess,safeSecret,integer,HttpError} from './core.js';
import {analyze} from './intelligence.js';

const storageHeaders=env=>({authorization:`Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,apikey:env.SUPABASE_SERVICE_ROLE_KEY});
const objectPath=(bucket,path)=>[bucket,...path.split('/')].map(encodeURIComponent).join('/');
export async function storage(env,path,options={}){
  check(env.SUPABASE_URL&&env.SUPABASE_SERVICE_ROLE_KEY,503,'Private storage is not configured');
  const r=await fetch(`${env.SUPABASE_URL}/storage/v1/${path}`,{...options,headers:{...storageHeaders(env),...options.headers},signal:AbortSignal.timeout(30000)});
  if(!r.ok){await r.body?.cancel();throw new HttpError(502,`Private storage request failed (${r.status})`);}return r;
}
export async function signedDownload(env,bucket,path,expires=900){
  const r=await storage(env,`object/sign/${objectPath(bucket,path)}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({expiresIn:expires})});
  const data=await r.json();const signed=data.signedURL||data.signedUrl;check(signed,502,'Storage signing failed');
  return signed.startsWith('http')?signed:`${env.SUPABASE_URL}/storage/v1${signed}`;
}
export async function purgeAudioObject(env,bucket,path){
  check(env.SUPABASE_URL&&env.SUPABASE_SERVICE_ROLE_KEY,503,'Private storage is not configured');
  check(bucket===env.SUPABASE_STORAGE_BUCKET,400,'Invalid storage bucket');
  const target=`object/${objectPath(bucket,path)}`;
  const r=await fetch(`${env.SUPABASE_URL}/storage/v1/${target}`,{method:'DELETE',headers:storageHeaders(env),signal:AbortSignal.timeout(15000)});
  if(r.status===200||r.status===204||r.status===404){await r.body?.cancel();return {ok:true,status:r.status};}
  const detail=await r.text().catch(()=>'');throw new Error(`Storage deletion failed (${r.status}): ${detail.slice(0,200)}`);
}
export async function safeCleanupRecordingAudio(db,env,recording,meetingPublicId){
  if(recording.is_audio_purged)return {purged:true,already:true};
  if(recording.retention_policy&&recording.retention_policy!=='ephemeral_transcript_only')return {purged:false,reason:'retention_policy_retained'};
  if(!recording.storage_path||!recording.storage_path.startsWith(`${meetingPublicId}/`))throw new Error('Tenant storage path mismatch');
  const activeJob=await db.one("SELECT id FROM ai_jobs WHERE recording_id=$1 AND status IN ('RUNNING','QUEUED') AND (status<>'RUNNING' OR started_at > now() - interval '10 minutes') LIMIT 1",[recording.id]);
  if(activeJob)return {purged:false,reason:'active_job_running'};
  try{
    await purgeAudioObject(env,recording.storage_bucket,recording.storage_path);
    await db.update('meeting_recordings','id=$1',[recording.id],{is_audio_purged:true,audio_purged_at:now(),cleanup_error:null});
    return {purged:true};
  }catch(err){
    const msg=String(err?.message||err).slice(0,1000);
    await db.rows('UPDATE meeting_recordings SET cleanup_retry_count=cleanup_retry_count+1, cleanup_error=$2 WHERE id=$1',[recording.id,msg]);
    return {purged:false,error:msg};
  }
}
async function recordingCompany(db,m){return m.company_id||(await db.one('SELECT company_id FROM company_members WHERE user_id=$1 ORDER BY created_at LIMIT 1',[m.owner_id]))?.company_id||`personal:${m.owner_id}`;}
async function newRecording(db,user,m,fileType='audio/webm'){
  const id=uid(),bucket='meeting-recordings';
  return db.insert('meeting_recordings',{id,meeting_id:m.public_id,company_id:await recordingCompany(db,m),uploaded_by_user_id:user.public_id,session_id:uid(),source:'client_mixed_audio',
    storage_backend:'supabase',storage_bucket:bucket,storage_path:`${m.public_id}/${id}/recording.webm`,original_filename:'recording.webm',file_type:fileType,file_size_bytes:0,processing_status:'RECORDING',
    is_audio_purged:false,retention_policy:'ephemeral_transcript_only',cleanup_retry_count:0});
}
async function enqueue(db,env,m,recording,user){
  check(recording.file_size_bytes>0,409,'Recording has not been uploaded');
  const job=await db.one(`INSERT INTO ai_jobs(id,public_id,created_at,updated_at,meeting_id,recording_id,company_id,requested_by_user_id,job_type,status,current_stage,retry_count,max_retries,provider)
    VALUES($1,$2,now(),now(),$3,$4,$5,$6,'MEETING_AI_PIPELINE','QUEUED','QUEUED',0,3,'cloudflare')
    ON CONFLICT(recording_id,job_type) DO UPDATE SET updated_at=now() RETURNING *`,[uid(),publicId('JOB'),m.public_id,recording.id,recording.company_id,user.public_id]);
  if(!['RUNNING','COMPLETED'].includes(job.status)){
    await env.AI_JOBS.send({job_id:job.public_id});
    await db.update('meeting_recordings','id=$1',[recording.id],{processing_status:'QUEUED'});
  }
  return {...recording,ai_job_id:job.public_id,processing_status:job.status==='COMPLETED'?'COMPLETED':'QUEUED'};
}
export async function callbackRoutes(c){
  const {path,method,request,env,db}=c,match=path.match(/^\/ai-jobs\/([^/]+)\/cloudflare\/(context|result|fail)$/);
  if(!match)return;
  check(await safeSecret(request.headers.get('x-meetvault-worker-secret'),env.CLOUDFLARE_AI_CALLBACK_SECRET),401,'Invalid worker secret');
  const [,id,action]=match,job=check(await db.one('SELECT * FROM ai_jobs WHERE public_id=$1',[id]),404,'AI job not found');
  const recording=check(await db.one('SELECT * FROM meeting_recordings WHERE id=$1',[job.recording_id]),404,'Recording not found');
  const m=check(await db.one('SELECT * FROM meetings WHERE public_id=$1 AND deleted_at IS NULL',[job.meeting_id]),404,'Meeting not found');
  if(action==='context'&&method==='GET'){
    if(job.status==='COMPLETED')return json({completed:true,job_id:id});
    check(!recording.is_audio_purged,410,'Recording audio has already been purged under retention policy');
    check(job.retry_count<job.max_retries,409,'Job retry limit reached');
    check(recording.storage_bucket===env.SUPABASE_STORAGE_BUCKET&&recording.storage_path.startsWith(`${m.public_id}/`),409,'Invalid recording path');
    const claimed=await db.one("UPDATE ai_jobs SET status='RUNNING',current_stage='FETCHING_AUDIO',started_at=now(),retry_count=retry_count+1,updated_at=now() WHERE public_id=$1 AND (status<>'RUNNING' OR started_at<now()-interval '5 minutes') RETURNING public_id",[id]);
    if(!claimed)return json({processing:true,job_id:id});
    return json({job_id:id,meeting_id:m.public_id,meeting_title:m.title,recording_id:recording.id,recording_url:await signedDownload(env,recording.storage_bucket,recording.storage_path,3600),file_type:recording.file_type,duration_seconds:recording.duration_seconds});
  }
  if(action==='fail'&&method==='POST'){
    const b=await body(request),error=String(b.error||'AI processing failed').slice(0,1000);
    const isPermanent=(job.retry_count>=job.max_retries);
    await db.tx(async()=>{
      await db.update('ai_jobs','public_id=$1',[id],{status:'FAILED',error_message:error,failed_at:now()});
      await db.update('meeting_recordings','id=$1',[recording.id],{processing_status:'FAILED',processing_error:error});
      await db.update('meetings','public_id=$1',[m.public_id],{transcription_status:'failed',transcription_error:error,analysis_status:'failed',analysis_error:error});
    });
    if(isPermanent){await safeCleanupRecordingAudio(db,env,recording,m.public_id);}
    return json({ok:true,job_id:id,permanent_failure:isPermanent});
  }
  if(action==='result'&&method==='POST'){
    if(job.status==='COMPLETED')return json({ok:true,job_id:id,already_completed:true});
    const b=await body(request,1048576);let segments=Array.isArray(b.segments)?b.segments:[];
    if(!segments.length&&b.transcription_text)segments=[{text:b.transcription_text,start_time:0,end_time:recording.duration_seconds||0,speaker_label:'SPEAKER_UNASSIGNED'}];
    check(segments.length>0&&segments.length<=500,422,'Invalid transcript segments');
    const valid=segments.map((s,i)=>({
      segment_id:`${recording.id}:${i}`,
      text:text(s.text,12000),
      start_time:Math.max(0,Number(s.start_time)||0),
      end_time:Math.max(Number(s.start_time)||0,Number(s.end_time)||0),
      speaker:String(s.speaker_label||'SPEAKER_UNASSIGNED').slice(0,100),
      attribution_status:['unverified','confirmed'].includes(s.attribution_status)?s.attribution_status:(s.speaker_label&&!['SPEAKER_UNASSIGNED','SPEAKER_UNKNOWN','UNKNOWN'].includes(s.speaker_label)?'unverified':'unknown')
    }));
    await db.tx(async()=>{
      // One parameterized statement instead of a query for every segment; idempotent on conflict.
      await db.rows(`INSERT INTO transcript_segments(id,created_at,updated_at,meeting_id,recording_id,segment_id,speaker_label,speaker_confirmed,start_time,end_time,text,attribution_status)
        SELECT gen_random_uuid(),now(),now(),$1,$2,x.segment_id,x.speaker,false,x.start_time,x.end_time,x.text,x.attribution_status
        FROM jsonb_to_recordset($3::jsonb) AS x(segment_id varchar,text varchar,start_time float,end_time float,speaker varchar,attribution_status varchar)
        ON CONFLICT(meeting_id,segment_id) DO UPDATE SET text=excluded.text,start_time=excluded.start_time,end_time=excluded.end_time,speaker_label=excluded.speaker_label,attribution_status=excluded.attribution_status,updated_at=now()`,[m.public_id,recording.id,JSON.stringify(valid)]);
      await db.update('meetings','public_id=$1',[m.public_id],{transcription_status:'completed',transcription_error:null,analysis_status:'processing'});
      await db.update('ai_jobs','public_id=$1',[id],{current_stage:'EXTRACTING_INTELLIGENCE'});
    });
    try{await analyze(db,env,m);}catch(error){await db.update('meetings','public_id=$1',[m.public_id],{analysis_status:'failed',analysis_error:error.message});throw error;}
    await db.tx(async()=>{
      await db.update('ai_jobs','public_id=$1',[id],{status:'COMPLETED',current_stage:'COMPLETED',completed_at:now(),error_message:null});
      await db.update('meeting_recordings','id=$1',[recording.id],{processing_status:'COMPLETED',processing_error:null});
    });
    await safeCleanupRecordingAudio(db,env,recording,m.public_id);
    return json({ok:true,job_id:id,segments:valid.length});
  }
}
export async function mediaRoutes(c){
  const {path,method,request,env,db,user}=c;
  let match=path.match(/^\/meetings\/([^/]+)\/recordings(?:\/(auto\/start|auto\/stop|upload-url|complete|reconcile-cleanup|([^/]+)\/signed-url|([^/]+)\/status))?$/);
  if(match){const [,id,action,signedId,statusId]=match,m=await meetingAccess(db,user,id,method!=='GET'&&!signedId);
    if(method==='GET'&&!action)return json(await db.rows('SELECT * FROM meeting_recordings WHERE meeting_id=$1 AND deleted_at IS NULL ORDER BY created_at DESC',[id]));
    if(signedId&&method==='POST'){
      const r=check(await db.one('SELECT * FROM meeting_recordings WHERE id=$1 AND meeting_id=$2 AND deleted_at IS NULL AND file_size_bytes>0',[signedId,id]),404,'Recording not found');
      check(!r.is_audio_purged,410,'Recording audio has been purged under retention policy');
      return json({recording_id:r.id,url:await signedDownload(env,r.storage_bucket,r.storage_path),expires_in_seconds:900});
    }
    if(statusId&&method==='PATCH'){const b=await body(request);check(['FINALIZING','FAILED'].includes(b.processing_status),422,'Invalid client recording status');return json(await db.update('meeting_recordings','id=$1 AND meeting_id=$2',[statusId,id],{processing_status:b.processing_status,processing_error:typeof b.processing_error==='string'?b.processing_error.slice(0,1000):null}));}
    if(action==='auto/start'&&method==='POST'){
      const r=await db.one("SELECT * FROM meeting_recordings WHERE meeting_id=$1 AND processing_status IN ('RECORDING','STARTING') AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1",[id]);return json(r||await newRecording(db,user,m));
    }
    if(action==='auto/stop'&&method==='POST'){const r=await db.one("SELECT * FROM meeting_recordings WHERE meeting_id=$1 AND processing_status='RECORDING' ORDER BY created_at DESC LIMIT 1",[id]);check(r,404,'No active recording');return json(await db.update('meeting_recordings','id=$1',[r.id],{processing_status:'FINALIZING'}));}
    if(action==='upload-url'&&method==='POST'){
      const b=await body(request);check(integer(b.size,1,Number(env.MAX_RECORDING_UPLOAD_BYTES)||20971520,0)>0,422,'Recording size is required');
      check(['audio/webm','audio/ogg','audio/wav','audio/mp4','audio/flac','audio/mpeg','video/webm','video/mp4'].includes(String(b.content_type||'').split(';')[0]),415,'Unsupported recording format');
      let r=b.session_id?await db.one('SELECT * FROM meeting_recordings WHERE session_id=$1 AND meeting_id=$2 AND uploaded_by_user_id=$3 AND file_size_bytes=0',[b.session_id,id,user.public_id]):null;
      r=r||await newRecording(db,user,m,b.content_type);r=await db.update('meeting_recordings','id=$1',[r.id],{original_filename:String(b.filename||'recording.webm').slice(0,200),file_type:b.content_type,duration_seconds:integer(b.duration_seconds,0,86400,0),processing_status:'FINALIZING'});
      const response=await storage(env,`object/upload/sign/${objectPath(r.storage_bucket,r.storage_path)}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({upsert:false})});const data=await response.json();
      check(data.url,502,'Could not sign recording upload');return json({recording_id:r.id,session_id:r.session_id,upload_url:`${env.SUPABASE_URL}/storage/v1${data.url}`});
    }
    if(action==='complete'&&method==='POST'){
      const b=await body(request),r=check(await db.one('SELECT * FROM meeting_recordings WHERE id=$1 AND meeting_id=$2 AND uploaded_by_user_id=$3 AND deleted_at IS NULL',[b.recording_id,id,user.public_id]),404,'Recording not found');
      if(r.file_size_bytes>0)return json(await enqueue(db,env,m,r,user));
      const info=await (await storage(env,`object/info/${objectPath(r.storage_bucket,r.storage_path)}`)).json();
      const size=Number(info.metadata?.size||info.size);
      if(!(size>0&&size<=(Number(env.MAX_RECORDING_UPLOAD_BYTES)||20971520))){
        await purgeAudioObject(env,r.storage_bucket,r.storage_path).catch(()=>null);
        await db.update('meeting_recordings','id=$1',[r.id],{file_size_bytes:Math.max(0,size||0),processing_status:'REJECTED',is_audio_purged:true,audio_purged_at:now(),cleanup_error:'Upload size outside allowed limit'});
        check(false,413,'Recording size is outside the free upload limit');
      }
      const done=await db.update('meeting_recordings','id=$1',[r.id],{file_size_bytes:size,processing_status:'UPLOADED'});return json(await enqueue(db,env,m,done,user),201);
    }
    if(action==='reconcile-cleanup'&&method==='POST'){
      const unpurged=await db.rows("SELECT * FROM meeting_recordings WHERE meeting_id=$1 AND is_audio_purged=false AND processing_status IN ('COMPLETED','FAILED','REJECTED') ORDER BY created_at ASC",[id]);
      const results=[];for(const rec of unpurged)results.push({id:rec.id,...(await safeCleanupRecordingAudio(db,env,rec,id))});
      return json({meeting_id:id,reconciled:results.length,results});
    }
    if(!action&&method==='POST'){
      // Compatibility for older clients; the hosted UI uses direct signed upload.
      check(Number(request.headers.get('content-length')||0)<=20971520+65536,413,'Recording is too large');
      const form=await request.formData(),file=form.get('file');check(file instanceof File&&file.size>0&&file.size<=20971520,413,'Recording is missing or too large');
      check(/^(audio|video)\//.test(file.type),415,'Unsupported recording format');
      const r=await newRecording(db,user,m,file.type);await storage(env,`object/${objectPath(r.storage_bucket,r.storage_path)}`,{method:'POST',headers:{'content-type':file.type},body:file.stream(),duplex:'half'});
      return json(await enqueue(db,env,m,await db.update('meeting_recordings','id=$1',[r.id],{file_size_bytes:file.size,duration_seconds:integer(form.get('duration_seconds'),0,86400,0),processing_status:'UPLOADED'}),user),201);
    }
  }
  match=path.match(/^\/meetings\/([^/]+)\/ai-jobs$/);
  if(match&&method==='GET'){await meetingAccess(db,user,match[1]);return json(await db.rows('SELECT * FROM ai_jobs WHERE meeting_id=$1 ORDER BY created_at DESC LIMIT 50',[match[1]]));}
}
