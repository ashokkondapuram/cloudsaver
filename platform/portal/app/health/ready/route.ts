export const dynamic = 'force-dynamic';
export async function GET() {
  let ready = false;
  try {
    const sessionHealthy=process.env.PORTAL_SESSION_REDIS_URL
      ? import('../../../lib/server/session').then(m=>m.sessionStoreReady()).then(()=>true,()=>false)
      : Promise.resolve(true);
    const base = process.env.IDENTITY_SERVICE_URL || 'http://identity-service:8005';
    const response = await fetch(base.replace(/\/$/, '') + '/health/ready', {
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(3000),
    });
    ready = response.status === 200;
    ready = (await sessionHealthy) && ready;
    await response.body?.cancel();
  } catch { /* No credentials or dependency errors are exposed by probes. */ }
  return Response.json({status: ready ? 'ready' : 'unavailable'}, {
    status: ready ? 200 : 503, headers: {'Cache-Control': 'no-store'},
  });
}
