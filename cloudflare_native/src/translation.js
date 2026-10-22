import {Buffer} from 'node:buffer';
import {body,check,json,meetingAccess,sign,uid,HttpError} from './core.js';

export const LANGUAGES=Object.freeze({en:'English',ta:'Tamil',hi:'Hindi'});
export const TRANSLATION_TOPIC='meetvault.translation.v1';
const MAX_AUDIO=256044; // Eight seconds, 16 kHz mono PCM16 WAV.
const language=value=>check(Object.hasOwn(LANGUAGES,value),422,'Choose English, Tamil or Hindi')&&value;
const enabled=env=>env.LIVE_TRANSLATION_ENABLED==='true';

export function wavDuration(bytes){
  const b=Buffer.from(bytes);
  check(b.length>=44&&b.length<=MAX_AUDIO,413,'Send at most eight seconds of audio');
  check(b.toString('ascii',0,4)==='RIFF'&&b.toString('ascii',8,12)==='WAVE'&&b.toString('ascii',12,16)==='fmt '&&b.readUInt32LE(16)===16&&b.readUInt16LE(20)===1&&b.readUInt16LE(22)===1&&b.readUInt32LE(24)===16000&&b.readUInt32LE(28)===32000&&b.readUInt16LE(32)===2&&b.readUInt16LE(34)===16&&b.toString('ascii',36,40)==='data'&&b.readUInt32LE(40)===b.length-44&&b.readUInt32LE(4)===b.length-8,415,'Expected 16 kHz mono PCM16 WAV');
  const seconds=(b.length-44)/32000;check(Number.isInteger((b.length-44)/2)&&seconds>=0.4&&seconds<=8,422,'Audio must be between 0.4 and 8 seconds');return seconds;
}
async function audioBody(request){
  check(request.headers.get('content-type')?.split(';')[0]==='audio/wav',415,'Expected audio/wav');
  const reader=request.body?.getReader();check(reader,422,'Audio is required');const chunks=[];let size=0;
  try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>MAX_AUDIO){await reader.cancel();throw new HttpError(413,'Audio is too large');}chunks.push(Buffer.from(value));}}finally{reader.releaseLock();}
  return Buffer.concat(chunks,size);
}
export async function translateText(env,text,source,target){
  language(source);language(target);if(source===target)return text;
  const result=await env.AI.run('@cf/meta/m2m100-1.2b',{text,source_lang:source,target_lang:target});
  check(typeof result.translated_text==='string'&&result.translated_text.trim()&&result.translated_text.length<=3000,502,'Translation returned no usable text');return result.translated_text.trim();
}
async function joined(db,user,id){return check(await db.one("SELECT * FROM meeting_participants WHERE meeting_id=$1 AND user_id=$2 AND status='JOINED'",[id,user.public_id]),403,'Join this meeting before using translation');}
async function settings(db,id){return await db.one('SELECT * FROM meeting_translation_settings WHERE meeting_id=$1',[id])||{meeting_id:id,enabled:false,save_transcripts:false};}
const limit=(env,key,fallback,max)=>Math.max(8,Math.min(max,Number(env[key])||fallback));
async function broadcast(env,m,segment){
  const room=`meeting-${m.public_id}`,url=new URL(env.LIVEKIT_URL);url.protocol=url.protocol==='wss:'?'https:':url.protocol==='ws:'?'http:':url.protocol;
  const token=await sign({iss:env.LIVEKIT_API_KEY,video:{roomAdmin:true,room}},env.LIVEKIT_API_SECRET,60);
  const packet={type:'translation',segment_id:segment.id,meeting_id:m.public_id,speaker_id:segment.user_id,speaker_name:segment.speaker_name,source_language:segment.source_language,original_text:segment.original_text,translations:segment.translations,created_at:segment.created_at};
  const data=Buffer.from(JSON.stringify(packet)).toString('base64');
  // Server-originated data has no participant identity. Clients reject packets
  // on this topic when sent by an ordinary participant.
  const r=await fetch(`${url.origin}/twirp/livekit.RoomService/SendData`,{method:'POST',headers:{authorization:`Bearer ${token}`,'content-type':'application/json'},body:JSON.stringify({room,data,kind:'RELIABLE',topic:TRANSLATION_TOPIC}),signal:AbortSignal.timeout(5000)});
  if(!r.ok){await r.body?.cancel();throw new Error('Live delivery unavailable');}
}
export async function translationRoutes(c){
  const {path,method,request,env,db,user}=c,match=path.match(/^\/meetings\/([^/]+)\/translation(?:\/(preferences|audio|segments\/([^/]+)\/speech\/([a-z]+)))?$/);
  if(!match)return;const [,id,action,segmentId,target]=match,m=await meetingAccess(db,user,id,method==='POST'&&!action);
  if(!action&&method==='GET'){
    const config=await settings(db,id),pref=await db.one('SELECT source_language,target_language,share_audio FROM meeting_translation_preferences WHERE meeting_id=$1 AND user_id=$2',[id,user.public_id]);
    const targets=await db.rows("SELECT DISTINCT p.target_language FROM meeting_translation_preferences p JOIN meeting_participants mp ON mp.meeting_id=p.meeting_id AND mp.user_id=p.user_id WHERE p.meeting_id=$1 AND p.target_language IS NOT NULL AND p.updated_at>now()-interval '60 seconds' AND mp.status='JOINED'",[id]);
    const segments=await db.rows("SELECT id,user_id,speaker_name,source_language,original_text,translations,created_at,status FROM meeting_translation_segments WHERE meeting_id=$1 AND status='COMPLETED' AND created_at>now()-interval '45 seconds' ORDER BY created_at DESC LIMIT 20",[id]);
    const usage=await db.one('SELECT coalesce(sum(duration_seconds),0)::float AS seconds FROM meeting_translation_segments WHERE meeting_id=$1',[id]);
    return json({available:enabled(env),...config,preference:pref||{source_language:'en',target_language:null,share_audio:false},active_languages:targets.map(t=>t.target_language),segments:segments.reverse(),audio_seconds_used:usage.seconds,meeting_audio_limit_seconds:limit(env,'TRANSLATION_MEETING_AUDIO_SECONDS',300,3600),spoken_service_available:!!(env.TRANSLATION_SPEECH_URL&&env.TRANSLATION_SPEECH_KEY),voice_preservation:false});
  }
  if(!action&&method==='POST'){
    check(enabled(env),503,'Live translation is not enabled on this deployment');check(m.status!=='COMPLETED',409,'This meeting has ended');
    const b=await body(request);check(typeof b.enabled==='boolean'&&typeof b.save_transcripts==='boolean',422,'Choose whether to enable translation and save originals');
    const row=await db.one('INSERT INTO meeting_translation_settings(meeting_id,enabled,save_transcripts,updated_by,updated_at) VALUES($1,$2,$3,$4,now()) ON CONFLICT(meeting_id) DO UPDATE SET enabled=excluded.enabled,save_transcripts=excluded.save_transcripts,updated_by=excluded.updated_by,updated_at=now() RETURNING *',[id,b.enabled,b.save_transcripts,user.public_id]);return json(row);
  }
  if(action==='preferences'&&method==='PUT'){
    await joined(db,user,id);const b=await body(request),source=language(b.source_language),target=b.target_language===null?null:language(b.target_language);check(typeof b.share_audio==='boolean',422,'Microphone translation requires an explicit choice');
    return json(await db.one('INSERT INTO meeting_translation_preferences(meeting_id,user_id,source_language,target_language,share_audio,updated_at) VALUES($1,$2,$3,$4,$5,now()) ON CONFLICT(meeting_id,user_id) DO UPDATE SET source_language=excluded.source_language,target_language=excluded.target_language,share_audio=excluded.share_audio,updated_at=now() RETURNING source_language,target_language,share_audio',[id,user.public_id,source,target,b.share_audio]));
  }
  if(action==='audio'&&method==='POST'){
    check(enabled(env),503,'Live translation is disabled');await joined(db,user,id);check(m.status!=='COMPLETED',409,'This meeting has ended');
    const config=await settings(db,id);check(config.enabled,409,'The host has not enabled translation');
    const preference=await db.one("SELECT * FROM meeting_translation_preferences WHERE meeting_id=$1 AND user_id=$2 AND share_audio=true AND updated_at>now()-interval '60 seconds'",[id,user.public_id]);check(preference,403,'Enable microphone sharing for translation first');
    const requestId=c.url.searchParams.get('segment_id');check(/^[0-9a-f-]{36}$/i.test(requestId||''),422,'A segment UUID is required');
    const bytes=await audioBody(request),duration=wavDuration(bytes),hash=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
    const segment=await db.tx(async()=>{
      const scope=m.company_id||m.owner_id;
      await db.rows('SELECT pg_advisory_xact_lock(hashtext($1))',[`translation:${scope}`]);
      const existing=await db.one('SELECT * FROM meeting_translation_segments WHERE meeting_id=$1 AND user_id=$2 AND request_id=$3',[id,user.public_id,requestId]);
      if(existing){check(existing.audio_hash===hash,409,'Segment ID already belongs to different audio');return existing;}
      const usage=await db.one("SELECT coalesce(sum(duration_seconds) FILTER(WHERE meeting_id=$1),0)::float AS meeting_seconds,coalesce(sum(duration_seconds) FILTER(WHERE created_at>=date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),0)::float AS daily_seconds,count(*) FILTER(WHERE meeting_id=$1 AND user_id=$3 AND created_at>now()-interval '1 minute')::int AS recent FROM meeting_translation_segments WHERE budget_scope=$2",[id,scope,user.public_id]);
      check(usage.recent<12,429,'Translation is busy. Pause briefly before sending more speech');
      check(usage.meeting_seconds+duration<=limit(env,'TRANSLATION_MEETING_AUDIO_SECONDS',300,3600),429,'This meeting reached its translation pilot allowance');
      check(usage.daily_seconds+duration<=limit(env,'TRANSLATION_DAILY_AUDIO_SECONDS',600,7200),429,'This workspace reached its daily translation pilot allowance');
      const row=await db.one("INSERT INTO meeting_translation_segments(id,meeting_id,user_id,request_id,budget_scope,speaker_name,source_language,duration_seconds,audio_hash,status,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'PROCESSING',now()) RETURNING *",[uid(),id,user.public_id,requestId,scope,user.full_name||'Participant',preference.source_language,duration,hash]);return {...row,fresh:true};
    });
    if(!segment.fresh)return json(segment,segment.status==='PROCESSING'?202:200);
    try{
      const listeners=await db.rows("SELECT DISTINCT p.target_language FROM meeting_translation_preferences p JOIN meeting_participants mp ON mp.meeting_id=p.meeting_id AND mp.user_id=p.user_id WHERE p.meeting_id=$1 AND p.target_language IS NOT NULL AND p.updated_at>now()-interval '60 seconds' AND mp.status='JOINED'",[id]);
      check(listeners.length,409,'No participant has selected a translation language');
      const result=await env.AI.run('@cf/openai/whisper-large-v3-turbo',{audio:bytes.toString('base64'),task:'transcribe',language:preference.source_language,vad_filter:true,condition_on_previous_text:false});
      const original=String(result.text||'').trim();check(original.length<=2000,422,'Speech segment produced too much text');
      const translations={};if(original)for(const listener of listeners)translations[listener.target_language]=await translateText(env,original,preference.source_language,listener.target_language);
      const row=await db.tx(async()=>{
        // A host can disable capture while inference is in flight.
        const still=await db.one('SELECT enabled,save_transcripts FROM meeting_translation_settings WHERE meeting_id=$1',[id]);check(still?.enabled,409,'The host stopped translation');
        await joined(db,user,id);
        check((await db.one('SELECT share_audio FROM meeting_translation_preferences WHERE meeting_id=$1 AND user_id=$2',[id,user.public_id]))?.share_audio,409,'Microphone translation consent was withdrawn');
        if(original&&still.save_transcripts){
          const start=Math.max(0,(Date.now()-new Date(m.start_time||m.created_at).getTime())/1000-duration);
          await db.rows("INSERT INTO transcript_segments(id,created_at,updated_at,meeting_id,segment_id,speaker_label,speaker_user_id,participant_id,speaker_confirmed,attribution_status,start_time,end_time,text,processing_metadata) VALUES($1,now(),now(),$2,$3,$4,$5,$6,false,'self_reported',$7,$8,$9,$10) ON CONFLICT(meeting_id,segment_id) DO NOTHING",[uid(),id,`live-translation:${segment.id}`,String(user.full_name||user.public_id).slice(0,100),user.public_id,(await joined(db,user,id)).id,start,start+duration,original,JSON.stringify({source:'live_translation_microphone',source_language:preference.source_language,translations})]);
        }
        return db.one("UPDATE meeting_translation_segments SET original_text=$2,translations=$3,status='COMPLETED' WHERE id=$1 RETURNING *",[segment.id,original,JSON.stringify(translations)]);
      });
      try{if(original)await broadcast(env,m,row);}catch{console.warn(JSON.stringify({event:'translation_delivery_delayed',meeting_id:id}));}
      return json(row,201);
    }catch(e){await db.rows("UPDATE meeting_translation_segments SET status='FAILED',error_code=$2 WHERE id=$1",[segment.id,e instanceof HttpError?String(e.status):'AI_UNAVAILABLE']);if(e instanceof HttpError)throw e;throw new HttpError(503,'Translation is temporarily unavailable or its AI allocation is exhausted');}
  }
  if(segmentId&&method==='GET'){
    language(target);await joined(db,user,id);check(env.TRANSLATION_SPEECH_URL&&env.TRANSLATION_SPEECH_KEY,503,'Shared spoken translation is not configured; captions remain available');
    const segment=check(await db.one("SELECT * FROM meeting_translation_segments WHERE id=$1 AND meeting_id=$2 AND status='COMPLETED' AND created_at>now()-interval '2 minutes'",[segmentId,id]),404,'Translation audio expired');
    const translated=check(segment.translations[target],404,'This language was not requested');
    const endpoint=new URL(env.TRANSLATION_SPEECH_URL);check(endpoint.protocol==='https:',503,'Speech service must use HTTPS');
    const response=await fetch(endpoint,{method:'POST',headers:{authorization:`Bearer ${env.TRANSLATION_SPEECH_KEY}`,'content-type':'application/json','idempotency-key':`${segment.id}:${target}`},body:JSON.stringify({text:translated,language:target,voice:'standard'}),redirect:'error',signal:AbortSignal.timeout(15000)});
    check(response.ok&&/^audio\//.test(response.headers.get('content-type')||''),502,'Spoken translation is unavailable');
    return new Response(response.body,{headers:{'content-type':response.headers.get('content-type'),'cache-control':'private, no-store'}});
  }
}
