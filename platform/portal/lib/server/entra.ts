import {createHash, randomBytes} from 'node:crypto';
import {serverConfig} from './config';
import type {PortalSession} from './session';

const PENDING_TTL_MS = 10 * 60 * 1000;
export const OAUTH_STATE_COOKIE = 'cloudsaver_portal_oauth';

type Pending = {verifier: string; nonce: string; return_to: string; created_at: number};
const globalStore = globalThis as typeof globalThis & {__cloudsaverPortalPending?: Map<string, Pending>};
const pending: Map<string, Pending> = globalStore.__cloudsaverPortalPending ??= new Map();

export function entraConfigured() {
  const {tenantId, clientId, clientSecret} = serverConfig().entra;
  return Boolean(tenantId && clientId && clientSecret);
}

function authority() {
  return `https://login.microsoftonline.com/${encodeURIComponent(serverConfig().entra.tenantId)}/oauth2/v2.0`;
}

function scope() {
  return `openid profile offline_access ${serverConfig().entra.apiScope}`;
}

export function beginLogin(options: {returnTo: string; stepUp: boolean}) {
  const now = Date.now();
  for (const [key, value] of pending) if (now - value.created_at > PENDING_TTL_MS) pending.delete(key);
  const state = randomBytes(32).toString('base64url');
  const verifier = randomBytes(48).toString('base64url');
  const nonce = randomBytes(32).toString('base64url');
  pending.set(state, {verifier, nonce, return_to: options.returnTo, created_at: now});
  const {clientId, redirectUri} = serverConfig().entra;
  const params = new URLSearchParams({
    client_id: clientId,
    response_type: 'code',
    redirect_uri: redirectUri,
    response_mode: 'query',
    scope: scope(),
    state,
    nonce,
    code_challenge: createHash('sha256').update(verifier).digest('base64url'),
    code_challenge_method: 'S256',
  });
  if (options.stepUp) {
    params.set('prompt', 'login');
    params.set('max_age', '0');
  }
  return {state, url: `${authority()}/authorize?${params.toString()}`};
}

export function takePending(state: string): Pending | null {
  const entry = pending.get(state);
  pending.delete(state);
  if (!entry || Date.now() - entry.created_at > PENDING_TTL_MS) return null;
  return entry;
}

type TokenResponse = {access_token?: string; refresh_token?: string; id_token?: string; expires_in?: number; error?: string};

async function tokenRequest(form: Record<string, string>): Promise<TokenResponse> {
  const {clientId, clientSecret} = serverConfig().entra;
  const response = await fetch(`${authority()}/token`, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({client_id: clientId, client_secret: clientSecret, ...form}).toString(),
    cache: 'no-store',
    signal: AbortSignal.timeout(15_000),
  });
  const body = await response.json().catch(() => ({})) as TokenResponse;
  if (!response.ok || !body.access_token) throw new Error(body.error || `token endpoint returned ${response.status}`);
  return body;
}

export function exchangeCode(code: string, verifier: string) {
  const {redirectUri, apiScope} = serverConfig().entra;
  return tokenRequest({grant_type: 'authorization_code', code, redirect_uri: redirectUri, code_verifier: verifier, scope: `openid profile offline_access ${apiScope}`});
}

/** Decodes the id_token payload. The token comes straight from the token endpoint over TLS. */
export function idTokenClaims(idToken: string | undefined): Record<string, unknown> {
  if (!idToken) return {};
  const [, payload] = idToken.split('.');
  try {
    return JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** Refreshes the identity-service access token when it expires within two minutes. */
export async function ensureFreshCredential(session: PortalSession): Promise<boolean> {
  if (session.profile.auth_mode !== 'entra' || !session.credential_expires_at) return true;
  if (session.credential_expires_at - Date.now() > 120_000) return true;
  if (!session.refresh_token) return false;
  try {
    const tokens = await tokenRequest({grant_type: 'refresh_token', refresh_token: session.refresh_token, scope: scope()});
    session.credential = tokens.access_token as string;
    session.refresh_token = tokens.refresh_token || session.refresh_token;
    session.credential_expires_at = Date.now() + (tokens.expires_in ?? 3600) * 1000;
    return true;
  } catch {
    return false;
  }
}
