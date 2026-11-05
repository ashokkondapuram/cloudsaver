/**
 * Cloudflare Worker bridge for CloudSaver Code Mode.
 * Deploy with wrangler; set CLOUDFLARE_CODE_MODE_BRIDGE_URL to the worker /run route.
 */
const FORBIDDEN = /\b(import|export\s+(?:default|\*|{)|require\s*\(|eval\s*\(|Function\s*\(|fetch\s*\(|globalThis|process\.|Worker\s*\(|WebSocket\s*\()/i;
const SNIPPET = /^function\s+transform\s*\(\s*input\s*\)\s*\{[\s\S]+\}\s*$/;

function validateSnippet(snippet) {
  if (!snippet || typeof snippet !== 'string') throw new Error('Snippet is required.');
  if (snippet.length > 16384) throw new Error('Snippet exceeds 16 KB.');
  if (FORBIDDEN.test(snippet)) throw new Error('Snippet uses a forbidden construct.');
  if (!SNIPPET.test(snippet.trim())) throw new Error('Snippet must declare function transform(input) { ... }.');
}

async function verify(request, env, bodyBytes) {
  const secret = request.headers.get('X-CloudSaver-Code-Mode-Secret') || '';
  if (!secret || secret !== env.BRIDGE_SECRET) return false;
  const signature = request.headers.get('X-CloudSaver-Code-Mode-Signature') || '';
  if (!signature || signature.length !== 64) return false;
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(env.BRIDGE_SECRET),
    {name: 'HMAC', hash: 'SHA-256'},
    false,
    ['sign'],
  );
  const expected = await crypto.subtle.sign('HMAC', key, bodyBytes);
  const hex = [...new Uint8Array(expected)].map(b => b.toString(16).padStart(2, '0')).join('');
  return hex === signature;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== '/run' || request.method !== 'POST') {
      return new Response('Not found', {status: 404});
    }
    const bodyBytes = new Uint8Array(await request.arrayBuffer());
    if (!(await verify(request, env, bodyBytes))) {
      return new Response('Unauthorized', {status: 401});
    }
    let payload;
    try {
      payload = JSON.parse(new TextDecoder().decode(bodyBytes));
    } catch {
      return Response.json({status: 'failed', error: 'Invalid JSON body.'}, {status: 422});
    }
    try {
      validateSnippet(payload.snippet);
      const fn = new Function('input', `"use strict";\n${payload.snippet}\nreturn transform(input);`);
      const output = fn(payload.input);
      return Response.json({
        status: 'succeeded',
        output,
        worker_ref: 'cloudflare-code-mode-bridge',
        run_id: payload.run_id,
        tenant_id: payload.tenant_id,
      });
    } catch (error) {
      return Response.json({status: 'failed', error: String(error.message || error)}, {status: 422});
    }
  },
};
