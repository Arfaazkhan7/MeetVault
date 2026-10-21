import {openDb,currentUser,check,json,HttpError,verify,body} from './core.js';
import {accountRoutes} from './accounts.js';
import {meetingRoutes} from './meetings.js';
import {intelligenceRoutes} from './intelligence.js';
import {callbackRoutes,mediaRoutes} from './media.js';
import {extraRoutes} from './extras.js';

export function corsHeaders(request,env){
  const origin=request.headers.get('origin'),allowed=String(env.BACKEND_CORS_ORIGINS||'').split(',').map(v=>v.trim());
  const h=new Headers({'Vary':'Origin','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
  if(origin&&allowed.includes(origin)){h.set('Access-Control-Allow-Origin',origin);h.set('Access-Control-Allow-Credentials','true');h.set('Access-Control-Allow-Methods','GET,POST,PUT,PATCH,DELETE,OPTIONS');h.set('Access-Control-Allow-Headers','Authorization,Content-Type');h.set('Access-Control-Max-Age','600');}
  return h;
}
export async function handle(request,env,ctx,{connect=openDb}={}){
  const url=new URL(request.url),headers=corsHeaders(request,env),method=request.method;
  let db,response,verifiedClaims;const requestId=crypto.randomUUID();
  try {
    if(method==='OPTIONS'){
      check(headers.has('Access-Control-Allow-Origin'),403,'Origin not allowed');
      const requested=(request.headers.get('access-control-request-headers')||'').toLowerCase().split(',').map(v=>v.trim()).filter(Boolean);
      check(requested.every(h=>['authorization','content-type'].includes(h)),403,'Header not allowed');
      response=new Response(null,{status:204});
    }else if(url.pathname==='/'||url.pathname==='/login'||url.pathname==='/signup')response=Response.redirect(env.FRONTEND_PUBLIC_URL||'https://ai-meet-f8fd0.web.app',302);
    else {
      const path=url.pathname.replace(/^\/api\/v1(?=\/|$)/,'').replace(/\/$/,'')||'/';
      const publicAuth=method==='POST'&&['/auth/firebase/google','/auth/register','/auth/login','/auth/login/personal','/auth/login/workspace','/auth/refresh','/admin/login'].includes(path);
      const callback=/^\/ai-jobs\/[^/]+\/cloudflare\/(context|result|fail)$/.test(path);
      if(!publicAuth&&!callback&&path!=='/health'){
        const auth=request.headers.get('authorization')||'';check(auth.startsWith('Bearer '),401,'Sign in required');verifiedClaims=await verify(auth.slice(7),env.JWT_SECRET);
      }
      check(env.JWT_SECRET&&env.SUPABASE_SERVICE_ROLE_KEY&&env.LIVEKIT_API_SECRET,503,'Backend secrets are not configured');
      db=await connect(env);
      if(path==='/health'){await db.one('SELECT 1 AS ok');response=json({status:'ok',runtime:'cloudflare-native',features:['firebase-auth','meetings','recordings','cross-meeting-analysis']});}
      else {
        const user=publicAuth||callback?null:await currentUser(request,env,db,verifiedClaims),c={request,url,path,method,env,ctx,db,user};
        for(const route of [callbackRoutes,accountRoutes,meetingRoutes,intelligenceRoutes,mediaRoutes,extraRoutes]){response=await route(c);if(response)break;}
        if(!response)throw new HttpError(404,'Endpoint not found');
      }
    }
  }catch(e){
    const status=e instanceof HttpError?e.status:e.code==='23505'?409:500;
    // SQL errors can include secret values/parameters. Log only safe codes.
    console.error(JSON.stringify({request_id:requestId,path:url.pathname,status,code:e.code||e.name||'Error'}));
    response=json({detail:status===500?'The server could not complete this request.':status===409&&!(e instanceof HttpError)?'This record already exists.':e.message,request_id:requestId},status);
  }finally{if(db)await db.close().catch(()=>{});}
  const out=new Response(response.body,response);for(const [k,v] of headers)out.headers.set(k,v);out.headers.set('X-Request-ID',requestId);return out;
}
export default {fetch:handle};
