import {randomBytes} from 'node:crypto';
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

type Store = {sessions: Map<string, PortalSession>};
const globalStore = globalThis as typeof globalThis & {__cloudsaverPortalSessions?: Store};
const store: Store = globalStore.__cloudsaverPortalSessions ??= {sessions: new Map()};

function expired(session: PortalSession, now: number) {
  return now - session.created_at > MAX_AGE_MS || now - session.last_seen > IDLE_MS;
}

function sweep(now: number) {
  for (const [id, session] of store.sessions) if (expired(session, now)) store.sessions.delete(id);
}

export function createSession(input: Omit<PortalSession, 'id' | 'created_at' | 'last_seen'>): PortalSession {
  const now = Date.now();
  sweep(now);
  const session: PortalSession = {...input, id: randomBytes(32).toString('base64url'), created_at: now, last_seen: now};
  store.sessions.set(session.id, session);
  return session;
}

export function readSession(request: NextRequest, touch = true): PortalSession | null {
  const id = request.cookies.get(SESSION_COOKIE)?.value;
  if (!id) return null;
  const session = store.sessions.get(id);
  if (!session) return null;
  const now = Date.now();
  if (expired(session, now)) {
    store.sessions.delete(id);
    return null;
  }
  if (touch) session.last_seen = now;
  return session;
}

export function deleteSession(request: NextRequest) {
  const id = request.cookies.get(SESSION_COOKIE)?.value;
  if (id) store.sessions.delete(id);
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
