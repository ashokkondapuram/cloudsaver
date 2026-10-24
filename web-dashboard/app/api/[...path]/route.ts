import {NextRequest,NextResponse} from 'next/server';
export const dynamic='force-dynamic';
async function proxy(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){
  const {path}=await params;
  const resource=path.join('/');
  if(!/^v1\/(rules\/(?:effective|preview|overrides)|services\/(?:disks|public-ips|virtual-machines|app-service-plans)(?:\/comparison)?|me|onboarding\/claim|customer\/(?:me|users(?:\/invite|\/[a-fA-F0-9-]{36}\/(?:suspend|reactivate))?|ownership\/transfer|members(?:\/[a-fA-F0-9-]{36}(?:\/remove)?)?|service-accounts(?:\/[a-fA-F0-9-]{36})?|keys(?:\/[A-Za-z0-9]{12}\/(?:revoke|rotate))?|audit|access-export)|ai\/(?:targets|usage|assessments(?:\/[a-fA-F0-9-]+)?)|finops\/(?:imports|summary)|settings(?:\/access-test|\/ai(?:\/test-connection)?)?|providers|trends|scan-jobs(?:\/[a-fA-F0-9-]+)?|operations\/(?:reliability|deliveries(?:\/[a-fA-F0-9-]+\/(?:audit|retry))?)|policies\/terraform\/evaluate|gitops\/(?:targets|preview|requests(?:\/[a-fA-F0-9-]+)?)|auth\/consent-url|billing\/(?:entitlements|plans|plan(?:-requests)?)|ai-batches(?:\/[a-fA-F0-9-]+(?:\/cancel)?)?|resources\/[a-f0-9]{64}\/(?:history|decisions)|scans(?:\/[a-zA-Z0-9-]+(?:\/(?:kubernetes(?:\/patch-preview)?|remediation|remediation-terraform|cancel|analysis(?:\/resource)?|ai-risk-evaluation|ai-batches|resources(?:\/export|\/[a-f0-9]{64}(?:\/questions)?)?))?)?)$/.test(resource))return NextResponse.json({detail:'API route not found'},{status:404});
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
      headers:{Authorization:request.headers.get('authorization')||'','Content-Type':'application/json','X-Request-ID':request.headers.get('x-request-id')||crypto.randomUUID(),...(clientIp?{'X-Forwarded-For':clientIp}:{})},
      body:body as BodyInit|undefined,
      cache:'no-store',signal:AbortSignal.timeout(120000),
    });
    return new NextResponse(upstream.body,{status:upstream.status,headers:{'Content-Type':upstream.headers.get('content-type')||'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...Object.fromEntries(['x-request-id','retry-after','location'].flatMap(key=>{const value=upstream.headers.get(key);return value?[[key,value]]:[];}))}});
  }catch{return NextResponse.json({detail:'The API gateway could not be reached. Check server configuration and retry.'},{status:502});}
}
export {proxy as GET,proxy as POST,proxy as PUT,proxy as PATCH};
