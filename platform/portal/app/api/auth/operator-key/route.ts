import {createHash, timingSafeEqual} from 'node:crypto';
import type {NextRequest} from 'next/server';
import {serverConfig} from '../../../../lib/server/config';
import {checkOrigin, identityUnavailable, json, problem} from '../../../../lib/server/http';
import {fetchOperatorProfile, IdentityUnavailableError} from '../../../../lib/server/identity';
import {createSession, deleteSession, setSessionCookie} from '../../../../lib/server/session';

export const dynamic = 'force-dynamic';

const WINDOW_MS = 5 * 60 * 1000;
const MAX_ATTEMPTS = 10;
const globalStore = globalThis as typeof globalThis & {__cloudsaverPortalAttempts?: Map<string, number[]>};
const attempts: Map<string, number[]> = globalStore.__cloudsaverPortalAttempts ??= new Map();

function throttled(client: string) {
  const now = Date.now();
  const recent = (attempts.get(client) || []).filter(at => now - at < WINDOW_MS);
  attempts.set(client, recent);
  return recent.length >= MAX_ATTEMPTS;
}

function recordFailure(client: string) {
  attempts.set(client, [...(attempts.get(client) || []), Date.now()]);
}

export async function POST(request: NextRequest) {
  const rejected = checkOrigin(request);
  if (rejected) return rejected;
  const config = serverConfig();
  if (config.authMode !== 'operator_key') return problem(404, "Operator key sign-in isn't available.");
  if (!/^[0-9a-f]{64}$/.test(config.operatorKeyDigest)) return problem(503, "Operator sign-in isn't configured.");

  const client = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'local';
  if (throttled(client)) return problem(429, 'Too many sign-in attempts. Wait a few minutes and try again.');

  const body = await request.json().catch(() => null) as {key?: unknown} | null;
  const key = typeof body?.key === 'string' ? body.key.trim() : '';
  if (!key || key.length > 512) return problem(422, 'Enter your operator access key.');

  const supplied = createHash('sha256').update(key, 'utf8').digest();
  const expected = Buffer.from(config.operatorKeyDigest, 'hex');
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    recordFailure(client);
    return problem(401, "That key didn't work. Check it and try again.");
  }

  try {
    const {profile, status, detail} = await fetchOperatorProfile(key);
    if (!profile) {
      recordFailure(client);
      return problem(status === 403 ? 403 : 401, detail || "The identity service didn't accept this key.");
    }
    deleteSession(request);
    const session = createSession({credential: key, refresh_token: null, credential_expires_at: null, profile, signed_in_at: Date.now()});
    const response = json({signed_in: true, ...profile});
    setSessionCookie(response, request, session);
    return response;
  } catch (error) {
    if (error instanceof IdentityUnavailableError) return identityUnavailable();
    throw error;
  }
}
