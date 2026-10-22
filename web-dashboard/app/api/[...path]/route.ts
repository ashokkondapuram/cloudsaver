import {NextRequest,NextResponse} from 'next/server';
export const dynamic='force-dynamic';
async function proxy(request:NextRequest,{params}:{params:Promise<{path:string[]}>}){
  const {path}=await params;
  const resource=path.join('/');
  if(!/^v1\/(me|scans(?:\/[a-zA-Z0-9-]+(?:\/remediation)?)?)$/.test(resource))return NextResponse.json({detail:'API route not found'},{status:404});
  try{
    const gateway=process.env.API_GATEWAY_URL||'http://127.0.0.1:8000';
    const upstream=await fetch(`${gateway.replace(/\/$/,'')}/api/${resource}${request.nextUrl.search}`,{
      method:request.method,
      headers:{Authorization:request.headers.get('authorization')||'','Content-Type':'application/json'},
      body:request.method==='POST'?await request.text():undefined,
      cache:'no-store',signal:AbortSignal.timeout(120000),
    });
    return new NextResponse(upstream.body,{status:upstream.status,headers:{'Content-Type':upstream.headers.get('content-type')||'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
  }catch{return NextResponse.json({detail:'The API gateway could not be reached. Check server configuration and retry.'},{status:502});}
}
export {proxy as GET,proxy as POST};
