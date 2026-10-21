import {ACCESS_SQL,check,text,body,json,now,uid,publicId,meetingAccess,membership,projectAccess,sign,pick} from './core.js';

export async function participants(db,id){return db.rows('SELECT mp.*,mp.id AS participant_id,mp.user_id AS user_public_id,u.email,coalesce(u.full_name,mp.display_name) AS full_name FROM meeting_participants mp LEFT JOIN users u ON u.public_id=mp.user_id WHERE mp.meeting_id=$1 ORDER BY mp.created_at',[id]);}
export async function history(db,user){
  return db.rows(`SELECT m.*,m.public_id AS meeting_id,m.invite_code AS meeting_code,coalesce(m.start_time,m.created_at) AS started_at,m.end_time AS ended_at,
    CASE WHEN m.owner_id=$1 THEN 'HOST' ELSE coalesce(mine.role,'ATTENDEE') END AS my_role,
    mine.join_time AS my_join_time,mine.leave_time AS my_leave_time,mine.attendance_duration_seconds AS my_duration_seconds,
    coalesce((SELECT json_agg(json_build_object('participant_id',p.id,'user_public_id',p.user_id,'role',p.role,'status',p.status,'email',u.email,'full_name',coalesce(u.full_name,p.display_name),'attendance_duration_seconds',p.attendance_duration_seconds)) FROM meeting_participants p LEFT JOIN users u ON u.public_id=p.user_id WHERE p.meeting_id=m.public_id),'[]'::json) AS participants
    FROM meetings m LEFT JOIN meeting_participants mine ON mine.meeting_id=m.public_id AND mine.user_id=$1
    WHERE ${ACCESS_SQL} ORDER BY m.created_at DESC LIMIT 200`,[user.public_id]);
}
export async function createMeeting(db,user,payload,company=null){
  return db.tx(async()=>{
    const m=await db.insert('meetings',{public_id:publicId('MTG'),company_id:company,project_id:payload.project_id||null,owner_id:user.public_id,
      meeting_type:company?'WORKSPACE':'PERSONAL',title:text(payload.title,300),description:payload.description||null,status:'SCHEDULED',
      scheduled_start_time:payload.scheduled_start_time||null,invite_code:crypto.randomUUID().replaceAll('-','').slice(0,12).toUpperCase(),transcription_status:'pending',analysis_status:'pending'});
    await db.insert('meeting_participants',{user_id:user.public_id,meeting_id:m.public_id,role:'HOST',status:'INVITED',identity_mapping_status:'unmapped',is_guest:false});return m;
  });
}
export async function ensureParticipant(db,user,m){
  return db.one(`INSERT INTO meeting_participants(id,created_at,updated_at,user_id,meeting_id,role,status,identity_mapping_status,is_guest)
    VALUES($1,now(),now(),$2,$3,$4,'INVITED','verified',false) ON CONFLICT(user_id,meeting_id) DO UPDATE SET updated_at=now() RETURNING *`,[uid(),user.public_id,m.public_id,m.owner_id===user.public_id?'HOST':'ATTENDEE']);
}
export async function roomConnection(db,env,user,m,p){
  check(m.status!=='COMPLETED',409,'This meeting has ended');
  const identity=`${user.public_id}:${p.id}`,room=`meeting-${m.public_id}`;
  await db.update('meeting_participants','id=$1',[p.id],{livekit_identity:identity,identity_mapping_status:'verified'});
  const token=await sign({iss:env.LIVEKIT_API_KEY,sub:identity,name:user.full_name||user.email,
    nbf:Math.floor(Date.now()/1000)-5,video:{roomJoin:true,room,canPublish:true,canSubscribe:true,canPublishData:true},
    metadata:JSON.stringify({user_public_id:user.public_id,meeting_id:m.public_id,participant_id:p.id,role:p.role,is_guest:false,identity_mapping_status:'verified'})},env.LIVEKIT_API_SECRET,3600);
  return {meeting_id:m.public_id,meeting_title:m.title,room_name:room,livekit_url:env.LIVEKIT_URL,token,token_expires_at:new Date(Date.now()+3600000).toISOString(),participant:{...p,participant_id:p.id,user_public_id:p.user_id,email:user.email,full_name:user.full_name}};
}
export async function meetingRoutes(c){
  const {path,method,request,env,db,user}=c;
  if(path==='/meetings/history'&&method==='GET')return json(await history(db,user));
  if(path==='/meetings/personal'&&method==='GET')return json((await history(db,user)).filter(m=>m.meeting_type==='PERSONAL'));
  if(path==='/meetings/personal'&&method==='POST')return json(await createMeeting(db,user,await body(request)),201);
  let match=path.match(/^\/(companies|projects)\/([^/]+)\/meetings$/);
  if(match){const [,scope,id]=match;
    if(scope==='companies')await membership(db,user,id);else await projectAccess(db,user,id);
    if(method==='GET')return json(await db.rows(`SELECT m.* FROM meetings m WHERE ${ACCESS_SQL} AND ${scope==='companies'?'m.company_id':'m.project_id'}=$2 ORDER BY m.created_at DESC LIMIT 200`,[user.public_id,id]));
    if(method==='POST'&&scope==='companies'){const b=await body(request);if(b.project_id){const p=await projectAccess(db,user,b.project_id);check(p.company_id===id,422,'Project belongs to another workspace');}return json(await createMeeting(db,user,b,id),201);}
  }
  if(path==='/meetings/join'&&method==='POST'){
    const b=await body(request),code=text(b.invite_code,100).toUpperCase();
    const m=check(await db.one('SELECT * FROM meetings WHERE upper(invite_code)=$1 AND deleted_at IS NULL',[code]),404,'Invalid meeting code');
    check(m.status!=='COMPLETED',409,'This meeting has ended');
    return json(await roomConnection(db,env,user,m,await ensureParticipant(db,user,m)));
  }
  match=path.match(/^\/meetings\/([^/]+)(?:\/(start|end|participants|room\/connect|room\/join|room\/leave)(?:\/([^/]+))?)?$/);
  if(!match)return;
  const [,id,section,target]=match;
  const host=['start','end'].includes(section)||method==='PATCH'||(section==='participants'&&method==='POST');
  const m=await meetingAccess(db,user,id,host);
  if(!section&&method==='GET')return json(m);
  if(!section&&method==='PATCH'){const b=await body(request);if(b.title!==undefined)b.title=text(b.title,300);return json(await db.update('meetings','public_id=$1',[id],pick(b,['title','description','scheduled_start_time']))||m);}
  if(section==='participants'&&method==='GET')return json(await participants(db,id));
  if(section==='participants'&&method==='POST'){
    const b=await body(request);check(await db.one('SELECT public_id FROM users WHERE public_id=$1 AND deleted_at IS NULL',[b.user_public_id]),404,'User not found');
    const p=await ensureParticipant(db,{public_id:b.user_public_id},m);return json({...p,participant_id:p.id,user_public_id:p.user_id},201);
  }
  if(section==='participants'&&target&&method==='PATCH'){
    const b=await body(request);check(['INVITED','JOINED','LEFT','DECLINED'].includes(b.status),422,'Invalid participant status');
    const p=check(await db.update('meeting_participants','meeting_id=$1 AND user_id=$2',[id,target],{status:b.status}),404,'Participant not found');return json({...p,participant_id:p.id,user_public_id:p.user_id});
  }
  if(section==='room/connect'&&method==='POST')return json(await roomConnection(db,env,user,m,await ensureParticipant(db,user,m)));
  if(section==='room/join'&&method==='POST'){
    check(m.status!=='COMPLETED',409,'This meeting has ended');const p=await ensureParticipant(db,user,m);
    const joined=await db.one("UPDATE meeting_participants SET status='JOINED',join_time=CASE WHEN status='JOINED' THEN join_time ELSE now() END,leave_time=NULL,updated_at=now() WHERE id=$1 RETURNING *",[p.id]);
    if(m.status==='SCHEDULED')await db.update('meetings','public_id=$1',[id],{status:'LIVE',start_time:now()});
    return json({...joined,participant_id:joined.id,user_public_id:joined.user_id});
  }
  if(section==='room/leave'&&method==='POST'){
    const p=check(await db.one("UPDATE meeting_participants SET attendance_duration_seconds=CASE WHEN status='JOINED' AND join_time IS NOT NULL THEN coalesce(attendance_duration_seconds,0)+greatest(0,extract(epoch FROM (now()-join_time)))::int ELSE attendance_duration_seconds END,status='LEFT',leave_time=coalesce(leave_time,now()),updated_at=now() WHERE meeting_id=$1 AND user_id=$2 RETURNING *",[id,user.public_id]),404,'Participant not found');return json({...p,participant_id:p.id,user_public_id:p.user_id});
  }
  if(section==='start'&&method==='POST'){check(m.status!=='COMPLETED',409,'This meeting has ended');const started=await db.one("UPDATE meetings SET status='LIVE',start_time=coalesce(start_time,now()),updated_at=now() WHERE public_id=$1 RETURNING *",[id]);return json({meeting:started,...await roomConnection(db,env,user,started,await ensureParticipant(db,user,started))});}
  if(section==='end'&&method==='POST')return json(await db.tx(async()=>{
    await db.rows("UPDATE meeting_participants SET attendance_duration_seconds=coalesce(attendance_duration_seconds,0)+greatest(0,extract(epoch FROM(now()-join_time)))::int,leave_time=now(),status='LEFT',updated_at=now() WHERE meeting_id=$1 AND status='JOINED' AND join_time IS NOT NULL",[id]);
    return db.one("UPDATE meetings SET status='COMPLETED',end_time=coalesce(end_time,now()),duration_seconds=coalesce(duration_seconds,greatest(0,extract(epoch FROM(now()-start_time)))::int),updated_at=now() WHERE public_id=$1 RETURNING *",[id]);
  }));
}
