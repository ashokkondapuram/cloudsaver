import {NextRequest,NextResponse} from 'next/server';
export const dynamic='force-dynamic';
async function proxy(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){
  const {path}=await params;
  const resource=path.join('/');
  if(!/^v1\/(me|providers|trends|policies\/terraform\/evaluate|gitops\/(?:targets|preview|requests(?:\/[a-fA-F0-9-]+)?)|auth\/consent-url|billing\/(?:entitlements|checkout)|scans(?:\/[a-zA-Z0-9-]+(?:\/(?:remediation|remediation-terraform|cancel))?)?)$/.test(resource))return NextResponse.json({detail:'API route not found'},{status:404});
  let body:Uint8Array|undefined;
  if(request.method==='POST'){
    const reader=request.body?.getReader();
    const chunks:Uint8Array[]=[];let size=0;
    if(reader){while(true){const next=await reader.read();if(next.done)break;size+=next.value.byteLength;if(size>2000000){await reader.cancel();return NextResponse.json({detail:'Request exceeds the 2 MB limit'},{status:413});}chunks.push(next.value);}}
    body=new Uint8Array(size);let offset=0;for(const chunk of chunks){body.set(chunk,offset);offset+=chunk.byteLength;}
  }
  try{
    const gateway=process.env.API_GATEWAY_URL||'http://127.0.0.1:8000';
    const upstream=await fetch(`${gateway.replace(/\/$/,'')}/api/${resource}${request.nextUrl.search}`,{
      method:request.method,
      headers:{Authorization:request.headers.get('authorization')||'','Content-Type':'application/json'},
      body:body as BodyInit|undefined,
      cache:'no-store',signal:AbortSignal.timeout(120000),
    });
    return new NextResponse(upstream.body,{status:upstream.status,headers:{'Content-Type':upstream.headers.get('content-type')||'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
  }catch{return NextResponse.json({detail:'The API gateway could not be reached. Check server configuration and retry.'},{status:502});}
}
export {proxy as GET,proxy as POST};
