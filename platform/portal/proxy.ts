import {NextResponse, type NextRequest} from 'next/server';

const SESSION_COOKIE = 'cloudsaver_portal_session';

function contentSecurityPolicy(nonce: string) {
  const dev = process.env.NODE_ENV !== 'production';
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ''}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join('; ');
}

export function proxy(request: NextRequest) {
  const {pathname} = request.nextUrl;
  if (pathname === '/health/live' || pathname === '/health/ready') return NextResponse.next();
  if (pathname.startsWith('/api/')) return NextResponse.next();

  if (pathname !== '/sign-in' && !request.cookies.get(SESSION_COOKIE)) {
    const target = new URL('/sign-in', process.env.PORTAL_PUBLIC_URL || request.url);
    if (pathname !== '/') target.searchParams.set('return_to', pathname);
    return NextResponse.redirect(target);
  }

  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce);
  const headers = new Headers(request.headers);
  headers.set('x-nonce', nonce);
  headers.set('Content-Security-Policy', csp);
  const response = NextResponse.next({request: {headers}});
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  matcher: [{source: '/((?!_next/static|_next/image|favicon.ico).*)'}],
};
