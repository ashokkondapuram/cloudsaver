export const dynamic = 'force-dynamic';
export async function GET() {
  let ready = false;
  try {
    const base = process.env.API_GATEWAY_URL || 'http://127.0.0.1:8000';
    const response = await fetch(base.replace(/\/$/, '') + '/health/ready', {
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(3000),
    });
    ready = response.status === 200;
    await response.body?.cancel();
  } catch { /* Dependency failures affect readiness only. */ }
  return Response.json({status: ready ? 'ready' : 'unavailable'}, {
    status: ready ? 200 : 503, headers: {'Cache-Control': 'no-store'},
  });
}
