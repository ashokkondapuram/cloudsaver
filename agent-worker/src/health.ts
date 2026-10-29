import {createServer} from 'node:http';

export function healthState(clock: () => number = Date.now) {
  let progress = clock(), ready = false, stopping = false;
  return {
    touch(ok = true) { progress = clock(); ready = ok; },
    stop() { stopping = true; },
    status(path: string) {
      if (!['/health/live', '/health/ready'].includes(path)) return {code: 404, status: 'not_found'};
      const alive = !stopping && clock() - progress <= 120_000;
      const ok = alive && (path === '/health/live' || ready);
      return {code: ok ? 200 : 503, status: ok ? (path === '/health/live' ? 'alive' : 'ready') : 'unavailable'};
    },
  };
}

export function startHealth() {
  const state = healthState();
  const server = createServer((request, response) => {
    const result = state.status(request.url || '');
    response.writeHead(result.code, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
    response.end(JSON.stringify({status: result.status}));
  });
  server.listen(Number(process.env.CLOUDSAVER_WORKER_HEALTH_PORT || '8099'), process.env.CLOUDSAVER_WORKER_HEALTH_HOST || '0.0.0.0');
  server.unref();
  return {...state, close() { state.stop(); server.close(); }};
}
