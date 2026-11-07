import {randomBytes} from 'node:crypto';
import {SessionStore} from './session-store';
import {serverConfig} from './config';
import type {NextRequest, NextResponse} from 'next/server';
import {isProduction, type AuthMode} from './config';

export const SESSION_COOKIE = 'cloudsaver_portal_session';
const MAX_AGE_MS = 8 * 60 * 60 * 1000;
const IDLE_MS = 30 * 60 * 1000;
export const STEP_UP_MS = 15 * 60 * 1000;

export type OperatorProfile = {
  actor: string;
  display_name: string;
  roles: string[];
  auth_mode: AuthMode;
  provider_scoped_keys: boolean;
  environment: string;
  key_prefix: 'cs_test_' | 'cs_live_';
  billing_enabled: boolean;
  billing_provider: 'manual' | 'stripe';
};

export type PortalSession = {
  id: string;
  credential: string;
  refresh_token: string | null;
  credential_expires_at: number | null;
  profile: OperatorProfile;
  created_at: number;
  signed_in_at: number;
  last_seen: number;
};

let persistent: SessionStore | undefined;
function store() {
  return persistent ??= new SessionStore(process.env.PORTAL_SESSION_DB || '/tmp/cloudsaver-portal/sessions.sqlite', serverConfig().identityToken);
}
export function claimSessionRefresh(id: string) {return store().claimRefresh(id, Date.now());}
export function finishSessionRefresh(session: PortalSession, fence: number) {return store().finishRefresh(session.id,fence,session,Date.now());}
export function reloadSession(id: string) {return store().read<PortalSession>(id,Date.now(),false,IDLE_MS);}

export function createSession(input: Omit<PortalSession, 'id' | 'created_at' | 'last_seen'>): PortalSession {
  const now = Date.now();
  const session: PortalSession = {...input, id: randomBytes(32).toString('base64url'), created_at: now, last_seen: now};
  store().create(session.id, session, now+MAX_AGE_MS, now+IDLE_MS);
  return session;
}

export function readSession(request: NextRequest, touch = true): PortalSession | null {
  const id = request.cookies.get(SESSION_COOKIE)?.value;
  if (!id) return null;
  const session=store().read<PortalSession>(id,Date.now(),touch,IDLE_MS);
  if (session && touch) session.last_seen=Date.now();
  return session;
}

export function deleteSession(request: NextRequest) {
  const id = request.cookies.get(SESSION_COOKIE)?.value;
  if (id) store().delete(id);
}

export function hasRecentSignIn(session: PortalSession) {
  return Date.now() - session.signed_in_at <= STEP_UP_MS;
}

export function secureCookies(request: NextRequest) {
  const forwarded = request.headers.get('x-forwarded-proto');
  return isProduction() || forwarded === 'https' || request.nextUrl.protocol === 'https:';
}

export function setSessionCookie(response: NextResponse, request: NextRequest, session: PortalSession) {
  response.cookies.set(SESSION_COOKIE, session.id, {
    httpOnly: true, sameSite: 'strict', path: '/', secure: secureCookies(request), maxAge: MAX_AGE_MS / 1000,
  });
}

export function clearSessionCookie(response: NextResponse, request: NextRequest) {
  response.cookies.set(SESSION_COOKIE, '', {httpOnly: true, sameSite: 'strict', path: '/', secure: secureCookies(request), maxAge: 0});
}

export function savePending(id: string, value: unknown, ttl: number) {store().create('oauth:'+id,value,Date.now()+ttl,Date.now()+ttl);}
export function takePendingValue<T>(id: string): T|null {return store().take<T>('oauth:'+id,Date.now());}
