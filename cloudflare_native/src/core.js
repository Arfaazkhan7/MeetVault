import {Client} from 'pg';
import {SignJWT, jwtVerify, createRemoteJWKSet} from 'jose';

export class HttpError extends Error {
  constructor(status, message) {super(message);this.status=status;}
}
export function check(value, status=400, message='Invalid request') {
  if(!value) throw new HttpError(status,message);
  return value;
}
export function text(value,max=4000) {
  check(typeof value==='string' && value.trim().length>0 && value.length<=max,422,'Invalid or missing text');
  return value.trim();
}
export function integer(value,min,max,fallback) {
  if(value===undefined||value===null||value==='') return fallback;
  const n=Number(value);check(Number.isInteger(n)&&n>=min&&n<=max,422,'Invalid number');return n;
}
export const json=(value,status=200)=>Response.json(value,{status});
export const now=()=>new Date().toISOString();
export const uid=()=>crypto.randomUUID();
export function publicId(prefix) {return `${prefix}-${crypto.randomUUID()}`;}
export async function body(request,max=65536) {
  const reader=request.body?.getReader();let size=0;const chunks=[];
  if(!reader) return {};
  try {for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;
    if(size>max){await reader.cancel();throw new HttpError(413,'Request too large');}chunks.push(value);}}
  finally {reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const c of chunks){bytes.set(c,offset);offset+=c.length;}
  try {const parsed=JSON.parse(new TextDecoder().decode(bytes));check(parsed&&typeof parsed==='object'&&!Array.isArray(parsed),422);return parsed;}
  catch(e){if(e instanceof HttpError)throw e;throw new HttpError(400,'Invalid JSON');}
}
export async function openDb(env) {
  check(env.HYPERDRIVE?.connectionString,503,'Database is not configured');
  const client=new Client({connectionString:env.HYPERDRIVE.connectionString,connectionTimeoutMillis:10000,query_timeout:15000});
  await client.connect();
  return new Db(client);
}
export class Db {
  constructor(client){this.client=client;}
  async rows(sql,params=[]){return (await this.client.query(sql,params)).rows;}
  async one(sql,params=[]){return (await this.rows(sql,params))[0];}
  async tx(fn){await this.rows('BEGIN');try{const value=await fn(this);await this.rows('COMMIT');return value;}
    catch(e){await this.rows('ROLLBACK').catch(()=>{});throw e;}}
  async insert(table,values){
    check(/^[a-z_]+$/.test(table));
    const row={id:uid(),created_at:now(),updated_at:now(),...values};
    const keys=Object.keys(row);check(keys.every(k=>/^[a-z_]+$/.test(k)));
    return this.one(`INSERT INTO ${table} (${keys.join(',')}) VALUES (${keys.map((_,i)=>'$'+(i+1)).join(',')}) RETURNING *`,Object.values(row));
  }
  async update(table,where,params,values){
    check(/^[a-z_]+$/.test(table));const keys=Object.keys(values);if(!keys.length)return;
    check(keys.every(k=>/^[a-z_]+$/.test(k)));
    return this.one(`UPDATE ${table} SET ${keys.map((k,i)=>`${k}=$${params.length+i+1}`).join(',')},updated_at=now() WHERE ${where} RETURNING *`,[...params,...Object.values(values)]);
  }
  async close(){await this.client.end();}
}
const encoder=new TextEncoder();
export async function sign(claims,secret,seconds=3600){
  check(secret,503,'Signing is not configured');
  return new SignJWT(claims).setProtectedHeader({alg:'HS256',typ:'JWT'}).setIssuedAt().setExpirationTime(Math.floor(Date.now()/1000)+seconds).sign(encoder.encode(secret));
}
export async function verify(token,secret,type='access') {
  try {const {payload}=await jwtVerify(token,encoder.encode(secret),{algorithms:['HS256'],requiredClaims:['sub','exp','iat']});
    check(payload.type===type&&typeof payload.sub==='string',401,'Invalid token');return payload;}
  catch{throw new HttpError(401,'Invalid or expired session');}
}
export async function tokens(user,env){return {access_token:await sign({sub:user.public_id,type:'access'},env.JWT_SECRET,3600),
  refresh_token:await sign({sub:user.public_id,type:'refresh'},env.JWT_SECRET,604800),token_type:'bearer',public_id:user.public_id,user:publicUser(user)};}
export const publicUser=u=>({public_id:u.public_id,email:u.email,full_name:u.full_name,firebase_uid:u.firebase_uid,account_type:u.account_type||'personal'});
export async function currentUser(request,env,db,verifiedClaims){
  const h=request.headers.get('authorization')||'';check(h.startsWith('Bearer '),401,'Sign in required');
  const claims=verifiedClaims||await verify(h.slice(7),env.JWT_SECRET);
  return check(await db.one('SELECT public_id,email,full_name,firebase_uid,account_type FROM users WHERE public_id=$1 AND deleted_at IS NULL',[claims.sub]),401,'Account unavailable');
}
const firebaseKeys=createRemoteJWKSet(new URL('https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com'));
export async function firebaseClaims(token,project,keys=firebaseKeys){
  check(typeof token==='string'&&token.length<=16384,401,'Invalid Firebase token');
  try {const {payload}=await jwtVerify(token,keys,{algorithms:['RS256'],audience:project,issuer:`https://securetoken.google.com/${project}`,requiredClaims:['exp','iat','sub','aud','iss','auth_time']});
    const t=Date.now()/1000;check(typeof payload.sub==='string'&&payload.sub.length>0&&payload.sub.length<=128&&typeof payload.iat==='number'&&payload.iat<=t&&typeof payload.auth_time==='number'&&payload.auth_time<=t&&payload.email_verified===true&&typeof payload.email==='string',401,'Verified Firebase email required');return payload;
  }catch(e){if(e instanceof HttpError)throw e;throw new HttpError(401,'Invalid Firebase authentication token');}
}
export async function safeSecret(provided,expected){
  if(!provided||!expected)return false;
  const [a,b]=await Promise.all([crypto.subtle.digest('SHA-256',encoder.encode(provided)),crypto.subtle.digest('SHA-256',encoder.encode(expected))]);
  const x=new Uint8Array(a),y=new Uint8Array(b);let diff=0;for(let i=0;i<x.length;i++)diff|=x[i]^y[i];return diff===0;
}
export async function membership(db,user,company,min='MEMBER'){
  const m=await db.one('SELECT cm.* FROM company_members cm JOIN companies c ON c.public_id=cm.company_id WHERE cm.user_id=$1 AND cm.company_id=$2 AND c.deleted_at IS NULL',[user.public_id,company]);
  const ranks={MEMBER:0,PROJECT_MANAGER:1,COMPANY_ADMIN:2,SUPER_ADMIN:3};
  check(m&&ranks[m.role]>=ranks[min],403,'Workspace permission required');return m;
}
export async function projectAccess(db,user,id,admin=false){
  const p=check(await db.one('SELECT * FROM projects WHERE public_id=$1 AND deleted_at IS NULL',[id]),404,'Project not found');
  const cm=await membership(db,user,p.company_id);
  const pm=await db.one('SELECT * FROM project_members WHERE project_id=$1 AND user_id=$2',[id,user.public_id]);
  check(['SUPER_ADMIN','COMPANY_ADMIN'].includes(cm.role)||(pm&&(!admin||['OWNER','ADMIN','PROJECT_MANAGER'].includes(pm.role))),403,'Project permission required');return p;
}
export const ACCESS_SQL=`m.deleted_at IS NULL AND (m.owner_id=$1 OR EXISTS(SELECT 1 FROM meeting_participants mp WHERE mp.meeting_id=m.public_id AND mp.user_id=$1) OR (m.meeting_type='WORKSPACE' AND EXISTS(SELECT 1 FROM company_members cm WHERE cm.company_id=m.company_id AND cm.user_id=$1)))`;
export async function meetingAccess(db,user,id,host=false){
  const m=check(await db.one(`SELECT m.* FROM meetings m WHERE m.public_id=$2 AND ${ACCESS_SQL}`,[user.public_id,id]),404,'Meeting not found');
  if(host)check(m.owner_id===user.public_id||await db.one("SELECT id FROM meeting_participants WHERE meeting_id=$1 AND user_id=$2 AND role='HOST'",[id,user.public_id]),403,'Host permission required');return m;
}
export function pick(object,keys){return Object.fromEntries(keys.filter(k=>Object.hasOwn(object,k)).map(k=>[k,object[k]]));}
