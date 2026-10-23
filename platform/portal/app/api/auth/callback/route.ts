import {NextResponse, type NextRequest} from 'next/server';
import {serverConfig} from '../../../../lib/server/config';
import {exchangeCode, idTokenClaims, OAUTH_STATE_COOKIE, takePending} from '../../../../lib/server/entra';
import {redirectTo, safeReturnPath} from '../../../../lib/server/http';
import {fetchOperatorProfile, IdentityUnavailableError} from '../../../../lib/server/identity';
import {createSession, deleteSession, secureCookies, setSessionCookie} from '../../../../lib/server/session';

export const dynamic = 'force-dynamic';

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, char => `&#${char.charCodeAt(0)};`);
}

function fail(request: NextRequest, code: string) {
  const response = redirectTo(`/sign-in?error=${code}`);
  response.cookies.set(OAUTH_STATE_COOKIE, '', {httpOnly: true, sameSite: 'lax', path: '/api/auth', secure: secureCookies(request), maxAge: 0});
  return response;
}

export async function GET(request: NextRequest) {
  const config = serverConfig();
  if (config.authMode !== 'entra') return redirectTo('/sign-in');
  const params = request.nextUrl.searchParams;
  const state = params.get('state') || '';
  const code = params.get('code') || '';
  const cookieState = request.cookies.get(OAUTH_STATE_COOKIE)?.value || '';
  if (params.get('error')) return fail(request, params.get('error') === 'access_denied' ? 'access_denied' : 'sign_in_failed');
  if (!state || !code || state !== cookieState) return fail(request, 'sign_in_expired');
  const pending = takePending(state);
  if (!pending) return fail(request, 'sign_in_expired');

  let tokens;
  try {
    tokens = await exchangeCode(code, pending.verifier);
  } catch {
    console.error('portal sign-in: token exchange failed');
    return fail(request, 'sign_in_failed');
  }
  const claims = idTokenClaims(tokens.id_token);
  const audience = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (claims.nonce !== pending.nonce || !audience.includes(config.entra.clientId) || (claims.tid && claims.tid !== config.entra.tenantId)) {
    console.error('portal sign-in: id_token validation failed');
    return fail(request, 'sign_in_failed');
  }

  try {
    const {profile, status} = await fetchOperatorProfile(tokens.access_token as string);
    if (!profile) return fail(request, status === 403 ? 'not_authorized' : 'sign_in_failed');
    const authTime = typeof claims.auth_time === 'number' ? claims.auth_time * 1000 : Date.now();
    deleteSession(request);
    const session = createSession({
      credential: tokens.access_token as string,
      refresh_token: tokens.refresh_token || null,
      credential_expires_at: Date.now() + (tokens.expires_in ?? 3600) * 1000,
      profile,
      signed_in_at: Math.min(authTime, Date.now()),
    });
    // A same-origin page hop so the SameSite=Strict session cookie is sent on the next navigation.
    const target = escapeHtml(safeReturnPath(pending.return_to));
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=${target}"><title>Signing in…</title></head><body><p>Signing you in… <a href="${target}">Continue</a></p></body></html>`;
    const response = new NextResponse(html, {
      status: 200,
      headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"},
    });
    setSessionCookie(response, request, session);
    response.cookies.set(OAUTH_STATE_COOKIE, '', {httpOnly: true, sameSite: 'lax', path: '/api/auth', secure: secureCookies(request), maxAge: 0});
    return response;
  } catch (error) {
    if (error instanceof IdentityUnavailableError) return fail(request, 'identity_unavailable');
    throw error;
  }
}
