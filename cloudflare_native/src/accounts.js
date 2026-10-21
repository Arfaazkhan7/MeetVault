import {check,text,body,json,uid,publicId,publicUser,tokens,verify,firebaseClaims,membership,projectAccess,pick,HttpError} from './core.js';

export async function createWorkspace(db,user,name,domain=null){
  const company=await db.insert('companies',{public_id:publicId('CMP'),workspace_code:crypto.randomUUID().replaceAll('-','').slice(0,12).toUpperCase(),name:text(name,200),domain});
  await db.insert('company_members',{company_id:company.public_id,user_id:user.public_id,role:'SUPER_ADMIN'});
  return company;
}
async function createProject(db,user,company,payload){
  const p=await db.insert('projects',{public_id:publicId('PRJ'),company_id:company,name:text(payload.name,200),description:payload.description||null,status:'ACTIVE'});
  await db.insert('project_members',{project_id:p.public_id,user_id:user.public_id,role:'OWNER'});return p;
}
async function defaultWorkspace(db,user){
  const c=await createWorkspace(db,user,`${user.full_name||'My'}'s Personal Workspace`);
  await createProject(db,user,c.public_id,{name:'General',description:'Default project for meetings'});
}
export async function firebaseUser(db,claims){
  return db.tx(async()=>{
    const email=claims.email.toLowerCase().trim();
    await db.rows('SELECT pg_advisory_xact_lock(hashtext($1))',[`firebase:${email}`]);
    const old=await db.one('SELECT * FROM users WHERE firebase_uid=$1 OR lower(email)=$2 ORDER BY (firebase_uid=$1) DESC LIMIT 1',[claims.sub,email]);
    if(old){check(!old.deleted_at,403,'Account unavailable');check(!old.firebase_uid||old.firebase_uid===claims.sub,409,'This email is linked to another identity');
      if(!old.firebase_uid)return db.update('users','public_id=$1',[old.public_id],{firebase_uid:claims.sub});return old;}
    const user=await db.insert('users',{public_id:publicId('USR'),firebase_uid:claims.sub,email,full_name:claims.name||email.split('@')[0],account_type:'personal',hashed_password:null});
    await defaultWorkspace(db,user);return user;
  });
}
async function prehash(password){
  const bytes=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(password)));
  return btoa(String.fromCharCode(...bytes));
}
export async function accountRoutes(c){
  const {path,method,request,env,db,user}=c;
  if(path==='/auth/firebase/google'&&method==='POST'){
    const payload=await body(request);const claims=await firebaseClaims(payload.id_token,env.FIREBASE_PROJECT_ID);
    return json(await tokens(await firebaseUser(db,claims),env));
  }
  if(path==='/auth/register'&&method==='POST'){
    const b=await body(request),email=text(b.email,254).toLowerCase(),password=text(b.password,256);
    check(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)&&password.length>=8&&/[A-Z]/.test(password)&&/[a-z]/.test(password)&&/\d/.test(password),422,'Valid email and a strong password are required');
    const hashInput=await prehash(password);
    const created=await db.tx(async()=>{
      const hash=await db.one("SELECT extensions.crypt($1,extensions.gen_salt('bf',12)) AS value",[hashInput]);
      const u=await db.insert('users',{public_id:publicId('USR'),email,full_name:text(b.full_name,200),hashed_password:hash.value,account_type:b.account_type==='workspace'?'workspace':'personal'});
      await defaultWorkspace(db,u);return u;});return json(publicUser(created),201);
  }
  if(['/auth/login','/auth/login/personal','/auth/login/workspace','/admin/login'].includes(path)&&method==='POST'){
    const b=await body(request),email=text(b.email,254).toLowerCase();
    const u=await db.one("SELECT * FROM users WHERE lower(email)=$1 AND deleted_at IS NULL AND hashed_password IS NOT NULL AND extensions.crypt($2,replace(hashed_password,'$2b$','$2a$'))=replace(hashed_password,'$2b$','$2a$')",[email,await prehash(text(b.password,256))]);
    check(u,401,'Incorrect email or password');
    let company;
    if(path.endsWith('/workspace')){
      company=await db.one('SELECT c.* FROM companies c JOIN company_members cm ON cm.company_id=c.public_id WHERE cm.user_id=$1 AND c.deleted_at IS NULL AND (c.workspace_code=$2 OR c.public_id=$2)',[u.public_id,text(b.workspace_code,100)]);
      check(company,401,'Workspace membership required');
    }
    if(path==='/admin/login')check(String(env.SYSTEM_ADMIN_PUBLIC_IDS||'').split(',').map(x=>x.trim()).includes(u.public_id),403,'System administrator is not configured for this account');
    return json({...await tokens(u,env),workspace_id:company?.public_id||null});
  }
  if(path==='/auth/refresh'&&method==='POST'){
    const b=await body(request),claims=await verify(b.refresh_token,env.JWT_SECRET,'refresh');
    const u=check(await db.one('SELECT * FROM users WHERE public_id=$1 AND deleted_at IS NULL',[claims.sub]),401,'Account unavailable');return json(await tokens(u,env));
  }
  if(path==='/auth/logout'&&method==='POST')return json({message:'Logged out'});
  if(['/auth/me','/users/me'].includes(path)&&method==='GET')return json(publicUser(user));
  if(path==='/users/me'&&method==='PATCH'){
    const b=await body(request);if(b.full_name!==undefined)b.full_name=text(b.full_name,200);
    return json(publicUser(await db.update('users','public_id=$1',[user.public_id],pick(b,['full_name','phone','avatar_url']))||user));
  }
  if(path==='/companies'&&method==='GET')return json(await db.rows('SELECT c.*,cm.role FROM companies c JOIN company_members cm ON cm.company_id=c.public_id WHERE cm.user_id=$1 AND c.deleted_at IS NULL ORDER BY c.created_at',[user.public_id]));
  if(path==='/companies'&&method==='POST'){const b=await body(request);return json(await db.tx(()=>createWorkspace(db,user,b.name,b.domain)),201);}
  if(path==='/projects'&&method==='GET')return json(await db.rows("SELECT DISTINCT p.* FROM projects p JOIN company_members cm ON cm.company_id=p.company_id LEFT JOIN project_members pm ON pm.project_id=p.public_id AND pm.user_id=$1 WHERE cm.user_id=$1 AND p.deleted_at IS NULL AND (cm.role IN ('SUPER_ADMIN','COMPANY_ADMIN') OR pm.id IS NOT NULL) ORDER BY p.created_at",[user.public_id]));
  let match=path.match(/^\/companies\/([^/]+)(?:\/(members|projects)(?:\/([^/]+))?)?$/);
  if(match){const [,id,section,memberId]=match;const cm=await membership(db,user,id,method==='GET'?'MEMBER':'COMPANY_ADMIN');
    if(!section&&method==='GET')return json(await db.one('SELECT * FROM companies WHERE public_id=$1',[id]));
    if(section==='projects'&&method==='GET')return json(await db.rows("SELECT p.* FROM projects p WHERE company_id=$1 AND deleted_at IS NULL AND ($3::boolean OR EXISTS(SELECT 1 FROM project_members pm WHERE pm.project_id=p.public_id AND pm.user_id=$2))",[id,user.public_id,['SUPER_ADMIN','COMPANY_ADMIN'].includes(cm.role)]));
    if(section==='projects'&&method==='POST')return json(await db.tx(async()=>createProject(db,user,id,await body(request))),201);
    if(section==='members'&&method==='GET')return json(await db.rows('SELECT cm.*,u.email,u.full_name,u.public_id AS user_public_id FROM company_members cm JOIN users u ON u.public_id=cm.user_id WHERE cm.company_id=$1',[id]));
    if(section==='members'&&method==='POST'){
      const b=await body(request),role=b.role||'MEMBER';check(['MEMBER','PROJECT_MANAGER','COMPANY_ADMIN'].includes(role),422,'Invalid role');
      const target=check(await db.one('SELECT public_id FROM users WHERE (public_id=$1 OR lower(email)=$2) AND deleted_at IS NULL',[b.user_public_id||'',String(b.email||'').toLowerCase()]),404,'User not found');
      return json(await db.insert('company_members',{user_id:target.public_id,company_id:id,role}),201);
    }
    if(memberId&&section==='members'){
      const target=check(await db.one('SELECT * FROM company_members WHERE company_id=$1 AND user_id=$2',[id,memberId]),404,'Member not found');
      check(target.role!=='SUPER_ADMIN'&&memberId!==user.public_id,403,'Workspace owner cannot be changed here');
      if(method==='DELETE'){await db.rows('DELETE FROM company_members WHERE id=$1',[target.id]);return json({ok:true});}
      if(method==='PATCH'){const b=await body(request);check(['MEMBER','PROJECT_MANAGER','COMPANY_ADMIN'].includes(b.role),422,'Invalid role');return json(await db.update('company_members','id=$1',[target.id],{role:b.role}));}
    }
  }
  match=path.match(/^\/projects\/([^/]+)(?:\/(archive|members)(?:\/([^/]+))?)?$/);
  if(match){const [,id,section,memberId]=match;const p=await projectAccess(db,user,id,method!=='GET');
    if(!section&&method==='GET')return json(p);
    if(!section&&method==='PATCH'){const b=await body(request);if(b.name!==undefined)b.name=text(b.name,200);return json(await db.update('projects','public_id=$1',[id],pick(b,['name','description']))||p);}
    if(section==='archive'&&method==='POST')return json(await db.update('projects','public_id=$1',[id],{status:'ARCHIVED'}));
    if(section==='members'&&method==='GET')return json(await db.rows('SELECT pm.*,u.full_name,u.email,u.public_id AS user_public_id FROM project_members pm JOIN users u ON u.public_id=pm.user_id WHERE pm.project_id=$1',[id]));
    if(section==='members'&&method==='POST'){const b=await body(request);await membership(db,{public_id:b.user_public_id},p.company_id);check(['MEMBER','OWNER','ADMIN','PROJECT_MANAGER'].includes(b.role||'MEMBER'),422,'Invalid role');return json(await db.insert('project_members',{project_id:id,user_id:b.user_public_id,role:b.role||'MEMBER'}),201);}
    if(section==='members'&&memberId&&method==='DELETE'){check(memberId!==user.public_id,403,'Cannot remove your own project access');await db.rows('DELETE FROM project_members WHERE project_id=$1 AND user_id=$2',[id,memberId]);return json({ok:true});}
  }
}
