import {NextResponse,type NextRequest} from 'next/server';

export function proxy(request:NextRequest){
  const nonce=btoa(crypto.randomUUID());
  const csp=["default-src 'self'",`script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${process.env.NODE_ENV==='development'?" 'unsafe-eval'":''}`,"style-src 'self' 'unsafe-inline'","img-src 'self' data:","font-src 'self'","connect-src 'self'","object-src 'none'","base-uri 'none'","form-action 'self'","frame-ancestors 'none'"].join('; ');
  const headers=new Headers(request.headers);headers.set('x-nonce',nonce);headers.set('Content-Security-Policy',csp);
  const response=NextResponse.next({request:{headers}});
  response.headers.set('Content-Security-Policy',csp);response.headers.set('Cache-Control','private, no-store');
  if(request.nextUrl.protocol==='https:')response.headers.set('Strict-Transport-Security','max-age=31536000');
  return response;
}
export const config={matcher:[{source:'/((?!api/|_next/static|_next/image|favicon.ico).*)'}]};
