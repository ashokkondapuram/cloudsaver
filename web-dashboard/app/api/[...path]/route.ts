import {allowsBrowserRoute} from '../../../lib/generated/browser-routes';
import {NextRequest,NextResponse} from 'next/server';
export const dynamic='force-dynamic';
async function proxy(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){
  const {path}=await params;
  const resource=path.join('/');
  if(!allowsBrowserRoute(request.method,resource))return NextResponse.json({detail:'API route not found'},{status:404});
  let body:Uint8Array|undefined;
  if(['POST','PUT','PATCH'].includes(request.method)){
    const reader=request.body?.getReader();
    const chunks:Uint8Array[]=[];let size=0;
    if(reader){while(true){const next=await reader.read();if(next.done)break;size+=next.value.byteLength;if(size>2000000){await reader.cancel();return NextResponse.json({detail:'Request exceeds the 2 MB limit'},{status:413});}chunks.push(next.value);}}
    body=new Uint8Array(size);let offset=0;for(const chunk of chunks){body.set(chunk,offset);offset+=chunk.byteLength;}
  }
  // The Next.js server sets x-forwarded-for to the socket peer; the gateway trusts it only from this container.
  const clientIp=(request.headers.get('x-forwarded-for')||'').split(',').pop()?.trim()||'';
  try{
    const gateway=process.env.API_GATEWAY_URL||'http://127.0.0.1:8000';
    const upstream=await fetch(`${gateway.replace(/\/$/,'')}/api/${resource}${request.nextUrl.search}`,{
      method:request.method,
      headers:{Authorization:request.headers.get('authorization')||'',...Object.fromEntries(['idempotency-key','if-match'].flatMap(k=>{const v=request.headers.get(k);return v?[[k,v]]:[];})),'Content-Type':'application/json',...(['v1/outcomes/evidence/receipts','v1/governance/evidence/receipts'].includes(resource)&&request.headers.get('x-evidence-signature')?{'X-Evidence-Signature':request.headers.get('x-evidence-signature')!}:{}),'X-Request-ID':request.headers.get('x-request-id')||crypto.randomUUID(),...(clientIp?{'X-Forwarded-For':clientIp}:{})},
      body:body as BodyInit|undefined,
      cache:'no-store',signal:AbortSignal.timeout(120000),
    });
    return new NextResponse(upstream.body,{status:upstream.status,headers:{'Content-Type':upstream.headers.get('content-type')||'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...Object.fromEntries(['x-request-id','retry-after','location','content-disposition','etag'].flatMap(key=>{const value=upstream.headers.get(key);return value?[[key,value]]:[];}))}});
  }catch{return NextResponse.json({detail:'The API gateway could not be reached. Check server configuration and retry.'},{status:502});}
}
export {proxy as GET,proxy as POST,proxy as PUT,proxy as PATCH,proxy as DELETE};
