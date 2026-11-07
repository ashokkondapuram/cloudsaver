/**
 * Code Mode remains unavailable until a separately isolated execution runtime
 * passes capability, resource-budget, replay and response-integrity acceptance.
 * Never evaluate submitted JavaScript inside the authenticated bridge itself.
 */
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== '/run' || request.method !== 'POST') {
      return new Response('Not found', {status: 404});
    }
    // Reject before reading an untrusted body or allocating execution resources.
    return Response.json(
      {status: 'failed', error: 'Isolated execution runtime is unavailable.'},
      {status: 503},
    );
  },
};
