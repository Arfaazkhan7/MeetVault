import {ACCESS_SQL,check,text,body,json,uid,now,publicId,meetingAccess,membership,projectAccess,pick,HttpError} from './core.js';
import {storage,signedDownload} from './media.js';
import {scopeMeetings} from './intelligence.js';
import {createWorkspace} from './accounts.js';

export async function extraRoutes(c){
  const {path,method,request,env,db,user,url}=c;
  if(path==='/analytics/dashboard'&&method==='GET'){
    const rows=await db.one(`WITH allowed AS(SELECT public_id FROM meetings m WHERE ${ACCESS_SQL}) SELECT
      (SELECT count(*)::int FROM allowed) AS meeting_count,
      (SELECT coalesce(sum(attendance_duration_seconds),0)::int FROM meeting_participants WHERE user_id=$1 AND meeting_id IN(SELECT public_id FROM allowed)) AS meeting_duration,
      (SELECT count(*)::int FROM meeting_participants WHERE meeting_id IN(SELECT public_id FROM allowed)) AS attendance,
      (SELECT count(*)::int FROM topics WHERE meeting_id IN(SELECT public_id FROM allowed)) AS topics,
      (SELECT count(*)::int FROM decisions WHERE meeting_id IN(SELECT public_id FROM allowed)) AS decisions,
      (SELECT count(*)::int FROM tasks WHERE meeting_id IN(SELECT public_id FROM allowed)) AS tasks,
      (SELECT count(*)::int FROM tasks WHERE meeting_id IN(SELECT public_id FROM allowed) AND lower(status) IN('open','pending')) AS open_tasks,
      (SELECT count(*)::int FROM tasks WHERE meeting_id IN(SELECT public_id FROM allowed) AND lower(status) IN('completed','done')) AS completed_tasks,
      (SELECT count(*)::int FROM questions WHERE meeting_id IN(SELECT public_id FROM allowed)) AS questions,
      (SELECT count(*)::int FROM risks WHERE meeting_id IN(SELECT public_id FROM allowed)) AS risks,
      (SELECT count(*)::int FROM commitments WHERE meeting_id IN(SELECT public_id FROM allowed)) AS commitments`,[user.public_id]);
    return json({...rows,recent_meetings:(await scopeMeetings(db,user,{})).slice(0,5),project_activity:[]});
  }
  let match=path.match(/^\/companies\/([^/]+)\/documents(?:\/(upload|search|([^/]+)(?:\/(pages|associate|download))?))?$/);
  if(match){const [,company,action,documentId,section]=match;await membership(db,user,company);
    if(documentId){
      const d=check(await db.one('SELECT * FROM documents WHERE public_id=$1 AND company_id=$2 AND deleted_at IS NULL',[documentId,company]),404,'Document not found');
      if(d.project_id)await projectAccess(db,user,d.project_id);if(d.meeting_id)await meetingAccess(db,user,d.meeting_id);
      if(method==='DELETE'){check(d.uploader_id===user.public_id||(await membership(db,user,company,'COMPANY_ADMIN')),403,'Document owner required');await db.update('documents','public_id=$1',[documentId],{deleted_at:now()});return json({ok:true});}
      if(section==='download'&&method==='GET'){
        const prefix=`supabase://${env.SUPABASE_DOCUMENTS_BUCKET}/`;check(d.file_url.startsWith(prefix),409,'Legacy document is not in private storage');
        return Response.redirect(await signedDownload(env,env.SUPABASE_DOCUMENTS_BUCKET,d.file_url.slice(prefix.length)),302);
      }
      if(section==='associate'&&method==='PATCH'){
        check(d.uploader_id===user.public_id,403,'Document owner required');const b=await body(request);
        if(b.project_id){const p=await projectAccess(db,user,b.project_id);check(p.company_id===company,422);}
        if(b.meeting_id){const m=await meetingAccess(db,user,b.meeting_id);check(m.company_id===company||m.owner_id===user.public_id,422);}
        return json(await db.update('documents','public_id=$1',[documentId],pick(b,['project_id','meeting_id']))||d);
      }
      if(method==='GET'){const pages=await db.rows('SELECT * FROM document_pages WHERE document_id=$1 ORDER BY page_number',[documentId]);return json(section==='pages'?pages:{...d,pages});}
    }
    if(action==='upload'&&method==='POST'){
      check(Number(request.headers.get('content-length')||0)<=5242880+65536,413,'Document limit is 5 MB');
      const form=await request.formData(),file=form.get('file');check(file instanceof File&&file.size>0&&file.size<=5242880,413,'Document limit is 5 MB');
      const pid=form.get('project_id')||null,mid=form.get('meeting_id')||null;
      if(pid){const p=await projectAccess(db,user,pid);check(p.company_id===company,422);}
      if(mid){const m=await meetingAccess(db,user,mid);check(m.company_id===company||m.owner_id===user.public_id,422);}
      const id=publicId('DOC'),key=`${company}/${id}/${uid()}`,bucket=env.SUPABASE_DOCUMENTS_BUCKET;
      await storage(env,`object/${[bucket,...key.split('/')].map(encodeURIComponent).join('/')}`,{method:'POST',headers:{'content-type':file.type||'application/octet-stream'},body:file.stream(),duplex:'half'});
      let extracted='';try{
        if(/\.(txt|md|csv|json)$/i.test(file.name))extracted=await file.text();
        else {const result=await env.AI.toMarkdown({name:file.name,blob:file});if(result.format!=='error')extracted=result.data||'';}
      }catch{/* The private original is retained if the converter/free allocation is unavailable. */}
      const pages=[];for(let i=0;i<Math.min(extracted.length,150000);i+=5000)pages.push({public_id:publicId('PAGE'),document_id:id,page_number:pages.length+1,text_content:extracted.slice(i,i+5000)});
      return json(await db.tx(async()=>{
        const doc=await db.insert('documents',{public_id:id,company_id:company,project_id:pid,meeting_id:mid,uploader_id:user.public_id,title:String(form.get('title')||file.name).slice(0,300),file_name:file.name.slice(0,200),file_type:file.name.split('.').pop().toLowerCase(),file_size:file.size,file_url:`supabase://${bucket}/${key}`,status:pages.length?'PROCESSED':'UPLOADED_UNINDEXED',page_count:pages.length});
        if(pages.length)await db.rows(`INSERT INTO document_pages(id,created_at,updated_at,public_id,document_id,page_number,text_content) SELECT gen_random_uuid(),now(),now(),x.public_id,x.document_id,x.page_number,x.text_content FROM jsonb_to_recordset($1::jsonb) AS x(public_id varchar,document_id varchar,page_number int,text_content varchar)`,[JSON.stringify(pages)]);
        return doc;
      }),201);
    }
    if(method==='GET'){
      const query=action==='search'?text(url.searchParams.get('query')||url.searchParams.get('q'),1000):null;
      const docs=await db.rows(`SELECT d.* FROM documents d WHERE d.company_id=$2 AND d.deleted_at IS NULL
        AND (d.project_id IS NULL OR EXISTS(SELECT 1 FROM project_members pm WHERE pm.project_id=d.project_id AND pm.user_id=$1) OR EXISTS(SELECT 1 FROM company_members cm WHERE cm.company_id=d.company_id AND cm.user_id=$1 AND cm.role IN('SUPER_ADMIN','COMPANY_ADMIN')))
        AND (d.meeting_id IS NULL OR EXISTS(SELECT 1 FROM meetings m WHERE m.public_id=d.meeting_id AND ${ACCESS_SQL}))
        AND ($3::text IS NULL OR d.title ILIKE '%'||$3||'%' OR EXISTS(SELECT 1 FROM document_pages dp WHERE dp.document_id=d.public_id AND dp.text_content ILIKE '%'||$3||'%')) ORDER BY d.created_at DESC LIMIT 100`,[user.public_id,company,query]);
      return json(action==='search'?{total:docs.length,results:docs.map(document=>({document,matching_pages:[]}))}:docs);
    }
  }
  match=path.match(/^\/diarization\/meetings\/([^/]+)\/(speaker-mappings(?:\/([^/]+)(?:\/(confirm))?)?|available-users|auto-map-speakers|diarize)$/);
  if(match){const [,mid,action,label,confirm]=match;await meetingAccess(db,user,mid,method!=='GET');
    if(action==='available-users'&&method==='GET')return json(await db.rows('SELECT u.public_id,u.full_name,u.email FROM users u JOIN meeting_participants p ON p.user_id=u.public_id WHERE p.meeting_id=$1',[mid]));
    if(label&&(method==='PUT'||method==='POST')){
      const b=method==='PUT'?await body(request):{},target=b.user_id||url.searchParams.get('user_id');
      const old=await db.one('SELECT * FROM speaker_mappings WHERE meeting_id=$1 AND speaker_label=$2',[mid,label]);
      const selected=target||old?.user_id;check(selected,422,'Select a meeting participant');
      check(await db.one('SELECT id FROM meeting_participants WHERE meeting_id=$1 AND user_id=$2',[mid,selected]),422,'User is not a meeting participant');
      const confirmed=Boolean(confirm||b.is_confirmed);
      return json(await db.tx(async()=>{
        const mapping=old?await db.update('speaker_mappings','id=$1',[old.id],{user_id:selected,is_confirmed:confirmed}):await db.insert('speaker_mappings',{meeting_id:mid,speaker_label:label,user_id:selected,is_confirmed:confirmed});
        await db.rows('UPDATE transcript_segments SET speaker_user_id=$3,user_id=$3,speaker_confirmed=$4,attribution_status=$5,updated_at=now() WHERE meeting_id=$1 AND speaker_label=$2',[mid,label,selected,confirmed,confirmed?'confirmed':'unconfirmed']);return mapping;
      }));
    }
    const mappings=await db.rows('SELECT * FROM speaker_mappings WHERE meeting_id=$1',[mid]);
    if(action==='diarize')return json({meeting_id:mid,status:'requires_speaker_mapping',message:'Automatic speaker identity is unavailable without a diarization provider. Map known speakers to participants to verify attribution.',speaker_mappings:mappings});
    return json({meeting_id:mid,mappings});
  }
  if(path.startsWith('/admin/')&&method==='GET'){
    // Global administration requires an explicit deployment allowlist. Workspace
    // ownership and an email prefix must never grant global access.
    check(String(env.SYSTEM_ADMIN_PUBLIC_IDS||'').split(',').map(x=>x.trim()).includes(user.public_id),403,'System administrator is not configured for this account');
    if(path==='/admin/workspaces')return json(await db.rows('SELECT c.*,(SELECT count(*)::int FROM company_members WHERE company_id=c.public_id) AS member_count,(SELECT count(*)::int FROM projects WHERE company_id=c.public_id) AS project_count FROM companies c WHERE deleted_at IS NULL'));
    if(path==='/admin/stats')return json(await db.one('SELECT (SELECT count(*)::int FROM users WHERE deleted_at IS NULL) AS total_users,(SELECT count(*)::int FROM companies WHERE deleted_at IS NULL) AS total_workspaces,(SELECT count(*)::int FROM projects WHERE deleted_at IS NULL) AS total_projects,(SELECT count(*)::int FROM meetings WHERE deleted_at IS NULL) AS total_meetings,(SELECT count(*)::int FROM meeting_recordings WHERE deleted_at IS NULL) AS total_recordings'));
  }
}
