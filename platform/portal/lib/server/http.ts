import {NextResponse, type NextRequest} from 'next/server';
import {serverConfig} from './config';

const NO_STORE = {'Cache-Control': 'no-store'};

export function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return NextResponse.json(body, {status, headers: {...NO_STORE, ...headers}});
}

export function problem(status: number, detail: string, extra: Record<string, unknown> = {}, headers: Record<string, string> = {}) {
  return json({detail, ...extra}, status, headers);
}

export function sessionEnded() {
  return problem(401, 'Your session has ended. Sign in again.', {}, {'X-Portal-Session': 'ended'});
}

export function stepUpRequired() {
  return problem(401, 'Sign in again to continue.', {step_up: true});
}

export function identityUnavailable() {
  return problem(503, 'The identity service is unavailable. Try again in a few minutes.');
}

/** Rejects cross-origin mutating requests; SameSite=Strict is the first line of defense. */
export function checkOrigin(request: NextRequest): NextResponse | null {
  if (['GET', 'HEAD', 'OPTIONS'].includes(request.method)) return null;
  const origin = request.headers.get('origin');
  if (!origin || origin !== serverConfig().publicOrigin) {
    return problem(403, "This request isn't allowed from this page. Reload the portal and try again.");
  }
  return null;
}

/** Returns a same-origin relative path, or "/" for anything that could redirect off-site. */
export function safeReturnPath(value: string | null | undefined) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return '/';
  if (value.startsWith('/api/') || value.startsWith('/sign-in')) return '/';
  return value;
}

export function redirectTo(path: string) {
  return NextResponse.redirect(new URL(path, serverConfig().publicUrl), {status: 303, headers: NO_STORE});
}
