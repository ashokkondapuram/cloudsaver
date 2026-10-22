export class ApiError extends Error {
  constructor(message: string, public status: number) {super(message);}
}

export async function api<T>(path: string, token: string, options: {body?: unknown; rawBody?: string; signal?: AbortSignal} = {}): Promise<T> {
  const hasBody = options.body !== undefined || options.rawBody !== undefined;
  const response = await fetch('/api/v1' + path, {
    method: hasBody ? 'POST' : 'GET',
    headers: {Authorization: 'Bearer ' + token, ...(hasBody ? {'Content-Type': 'application/json'} : {})},
    body: options.rawBody ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
    cache: 'no-store', signal: options.signal,
  });
  if (!response.ok) {
    let message = response.status === 401 ? 'Your session could not be verified. Connect again to continue.' : `Request could not be completed (${response.status}).`;
    try {const body = await response.json(); if (typeof body.detail === 'string') message = body.detail;} catch {}
    throw new ApiError(message, response.status);
  }
  return response.json();
}
