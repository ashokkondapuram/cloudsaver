import {randomUUID} from 'node:crypto';
import {NextResponse, type NextRequest} from 'next/server';
import {serverConfig} from '../../../../lib/server/config';
import {problem} from '../../../../lib/server/http';
import {UPSTREAM_TIMEOUT_MS} from '../../../../lib/server/identity';

export const dynamic = 'force-dynamic';

// Public path: no session or CSRF check. Signature verification happens only in identity-service.
const MAX_BODY_BYTES = 1024 * 1024;
const WINDOW_MS = 60 * 1000;
const MAX_REQUESTS = 60;
const globalStore = globalThis as typeof globalThis & {__platformWebhookHits?: Map<string, number[]>};
const hits: Map<string, number[]> = globalStore.__platformWebhookHits ??= new Map();

function rateLimited(client: string) {
  const now = Date.now();
  if (hits.size > 10_000) for (const [ip, times] of hits) if (!times.some(at => now - at < WINDOW_MS)) hits.delete(ip);
  const recent = (hits.get(client) || []).filter(at => now - at < WINDOW_MS);
  recent.push(now);
  hits.set(client, recent);
  return recent.length > MAX_REQUESTS;
}

async function readLimited(request: NextRequest): Promise<Uint8Array | null> {
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {body.set(chunk, offset); offset += chunk.byteLength;}
  return body;
}

export async function POST(request: NextRequest) {
  const client = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || request.headers.get('x-real-ip') || 'local';
  if (rateLimited(client)) return problem(429, 'Too many requests. Try again in a minute.', {}, {'Retry-After': '60'});

  const declared = Number(request.headers.get('content-length') || '0');
  if (declared > MAX_BODY_BYTES) return problem(413, 'This request is too large.');
  const body = await readLimited(request);
  if (!body) return problem(413, 'This request is too large.');

  const config = serverConfig();
  const headers: Record<string, string> = {
    'X-Service-Token': config.identityToken,
    'X-Request-ID': randomUUID(),
    'Content-Type': request.headers.get('content-type') || 'application/json',
    Accept: 'application/json',
  };
  const signature = request.headers.get('stripe-signature');
  if (signature) headers['Stripe-Signature'] = signature;

  let upstream: Response;
  try {
    upstream = await fetch(`${config.identityUrl}/billing/v1/webhooks/stripe`, {
      method: 'POST', headers, body: body as BodyInit, cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return problem(503, 'The identity service is unavailable. Try again in a few minutes.');
  }
  const text = await upstream.text();
  return new NextResponse(text || null, {
    status: upstream.status,
    headers: {'Content-Type': upstream.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store'},
  });
}
