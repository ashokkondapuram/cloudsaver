import {NextResponse, type NextRequest} from 'next/server';
import {serverConfig} from '../../../../lib/server/config';
import {beginLogin, entraConfigured, OAUTH_STATE_COOKIE} from '../../../../lib/server/entra';
import {redirectTo, safeReturnPath} from '../../../../lib/server/http';
import {secureCookies} from '../../../../lib/server/session';

export const dynamic = 'force-dynamic';

export function GET(request: NextRequest) {
  if (serverConfig().authMode !== 'entra') return redirectTo('/sign-in');
  if (!entraConfigured()) return redirectTo('/sign-in?error=not_configured');
  const params = request.nextUrl.searchParams;
  const stepUp = params.get('prompt') === 'login' || params.get('max_age') === '0';
  const {state, url} = beginLogin({returnTo: safeReturnPath(params.get('return_to')), stepUp});
  const response = NextResponse.redirect(url, {status: 303, headers: {'Cache-Control': 'no-store'}});
  // Lax so the cookie survives the top-level redirect back from Microsoft; it binds state to this browser.
  response.cookies.set(OAUTH_STATE_COOKIE, state, {httpOnly: true, sameSite: 'lax', path: '/api/auth', secure: secureCookies(request), maxAge: 600});
  return response;
}
