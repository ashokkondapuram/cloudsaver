export type Requester = typeof fetch;
export async function boundedRequest(url: string, init: RequestInit, request: Requester = fetch): Promise<{status: number; body: unknown; etag: string | null}> {
  const response = await request(url, {...init, redirect: 'error', signal: AbortSignal.timeout(45_000)});
  const reader = response.body?.getReader(); let bytes = 0; const chunks: Uint8Array[] = [];
  if (reader) {
    for (;;) {
      const part = await reader.read(); if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > 1_000_000) {await reader.cancel(); throw new Error('Response limit exceeded');}
      chunks.push(part.value);
    }
  }
  const text = Buffer.concat(chunks).toString('utf8');
  let body: unknown = null;
  if (text) {try {body = JSON.parse(text);} catch {body = null;}}
  return {status: response.status, body, etag: response.headers.get('etag')};
}
