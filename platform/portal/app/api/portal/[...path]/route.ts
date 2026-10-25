import {NextResponse, type NextRequest} from 'next/server';
import {serverConfig} from '../../../../lib/server/config';
import {ensureFreshCredential} from '../../../../lib/server/entra';
import {checkOrigin, identityUnavailable, problem, sessionEnded, stepUpRequired} from '../../../../lib/server/http';
import {identityHeaders, UPSTREAM_TIMEOUT_MS} from '../../../../lib/server/identity';
import {clearSessionCookie, deleteSession, hasRecentSignIn, readSession} from '../../../../lib/server/session';

export const dynamic = 'force-dynamic';

const MAX_BODY_BYTES = 1024 * 1024;
const ID = '[A-Za-z0-9._~:@-]+';
type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

const ROUTES: Array<[RegExp, Method[]]> = [
  [/^session$/, ['GET']],
  [/^knowledge\/publications$/, ['GET', 'POST']],
  [new RegExp(`^knowledge/publications/${ID}$`), ['PATCH']],
  [new RegExp(`^knowledge/publications/${ID}/review$`), ['POST']],
  [/^knowledge\/metrics$/, ['GET']],
  [/^customers$/, ['GET', 'POST']],
  [new RegExp(`^customers/${ID}$`), ['GET', 'PATCH', 'DELETE']],
  [new RegExp(`^customers/${ID}/(suspend|reactivate|bootstrap-key)$`), ['POST']],
  [/^workspaces$/, ['GET', 'POST']],
  [new RegExp(`^workspaces/${ID}$`), ['GET', 'PATCH', 'DELETE']],
  [new RegExp(`^workspaces/${ID}/scopes/(azure|aws|gcp|kubernetes)$`), ['PUT']],
  [new RegExp(`^workspaces/${ID}/(suspend|reactivate)$`), ['POST']],
  [new RegExp(`^workspaces/${ID}/keys$`), ['GET', 'POST']],
  [new RegExp(`^workspaces/${ID}/keys/revoke-all$`), ['POST']],
  [new RegExp(`^workspaces/${ID}/usage$`), ['GET']],
  [new RegExp(`^keys/${ID}$`), ['GET', 'PATCH']],
  [new RegExp(`^keys/${ID}/(rotate|revoke)$`), ['POST']],
  [new RegExp(`^keys/${ID}/usage$`), ['GET']],
  [new RegExp(`^customers/${ID}/(subscriptions|payments)$`), ['GET', 'POST']],
  [new RegExp(`^customers/${ID}/entitlements$`), ['GET']],
  [/^plans$/, ['GET', 'POST']],
  [new RegExp(`^plans/${ID}$`), ['GET', 'PATCH']],
  [new RegExp(`^plans/${ID}/retire$`), ['POST']],
  [/^plan-change-requests$/, ['GET']],
  [new RegExp(`^plan-change-requests/${ID}/(approve|reject)$`), ['POST']],
  [/^billing\/customers$/, ['GET']],
  [/^billing\/settings$/, ['GET', 'PUT']],
  [new RegExp(`^subscriptions/${ID}$`), ['GET', 'PATCH']],
  [new RegExp(`^subscriptions/${ID}/cancel$`), ['POST']],
  [new RegExp(`^payments/${ID}$`), ['PATCH']],
  [new RegExp(`^payments/${ID}/void$`), ['POST']],
  [/^platform-settings$/, ['GET', 'PUT']],
  [/^ai-policy$/, ['GET', 'PUT']],
  [/^access-checks$/, ['POST']],
  [new RegExp(`^access-checks/${ID}$`), ['GET']],
  [/^audit$/, ['GET']],
  [/^failures$/, ['GET']],
  [/^analysis\/rules$/, ['GET']],
  [new RegExp(`^workspaces/${ID}/analysis-rules$`), ['GET', 'PUT']],
];

const STEP_UP: Array<[RegExp, Method]> = [
  [new RegExp(`^workspaces/${ID}/keys/revoke-all$`), 'POST'],
  [new RegExp(`^workspaces/${ID}$`), 'DELETE'],
];

function allowed(path: string, method: Method) {
  return ROUTES.some(([pattern, methods]) => pattern.test(path) && methods.includes(method));
}

async function forward(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const method = request.method as Method;
  const rejected = checkOrigin(request);
  if (rejected) return rejected;

  const segments = (await context.params).path || [];
  if (segments.some(segment => !segment || segment === '.' || segment === '..' || !new RegExp(`^${ID}$`).test(segment))) {
    return problem(404, "This page doesn't exist.");
  }
  const path = segments.join('/');
  if (!allowed(path, method)) return problem(404, "This page doesn't exist.");

  const session = readSession(request);
  if (!session) return sessionEnded();
  if (STEP_UP.some(([pattern, m]) => m === method && pattern.test(path)) && !hasRecentSignIn(session)) return stepUpRequired();
  if (method !== 'GET' && !session.profile.roles.includes('PlatformOperator')) {
    return problem(403, "You don't have permission to make changes. Ask a platform operator for help.");
  }
  if (!(await ensureFreshCredential(session))) {
    deleteSession(request);
    const response = sessionEnded();
    clearSessionCookie(response, request);
    return response;
  }

  let body: ArrayBuffer | undefined;
  if (method !== 'GET' && method !== 'DELETE') {
    const declared = Number(request.headers.get('content-length') || '0');
    if (declared > MAX_BODY_BYTES) return problem(413, 'This request is too large.');
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) return problem(413, 'This request is too large.');
  }

  const segmentsEncoded = segments.map(encodeURIComponent).join('/');
  const url = `${serverConfig().identityUrl}/admin/v1/${segmentsEncoded}${request.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method,
      headers: identityHeaders(session.credential, {'Content-Type': 'application/json'}),
      body: body && body.byteLength ? body : undefined,
      cache: 'no-store',
      redirect: 'manual',
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return identityUnavailable();
  }

  if (upstream.status === 401) {
    deleteSession(request);
    const response = sessionEnded();
    clearSessionCookie(response, request);
    return response;
  }
  if (upstream.status >= 502 && upstream.status <= 504) return identityUnavailable();

  const text = await upstream.text();
  return new NextResponse(upstream.status === 204 ? null : text, {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') || 'application/json',
      'Cache-Control': 'no-store',
    },
  });
}

export {forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE};
