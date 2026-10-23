'use client';

export const GENERIC_ERROR = 'Something went wrong. If the issue persists, contact Support.';

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly stepUp = false) {
    super(message);
  }
}

type Query = Record<string, string | number | null | undefined>;

export function withQuery(path: string, query?: Query) {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

async function request<T>(url: string, init: {method?: string; body?: unknown} = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: init.method || 'GET',
      headers: init.body === undefined ? {Accept: 'application/json'} : {Accept: 'application/json', 'Content-Type': 'application/json'},
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: 'same-origin',
      cache: 'no-store',
    });
  } catch {
    throw new ApiError("We couldn't reach the portal. Check your connection and try again.", 0);
  }
  const text = await response.text();
  let body: unknown = null;
  try {body = text ? JSON.parse(text) : null;} catch {body = null;}
  if (!response.ok) {
    const detail = (body as {detail?: unknown} | null)?.detail;
    const stepUp = (body as {step_up?: unknown} | null)?.step_up === true;
    if (response.headers.get('X-Portal-Session') === 'ended' && typeof window !== 'undefined') {
      window.location.assign(`/sign-in?error=session_ended&return_to=${encodeURIComponent(window.location.pathname)}`);
    }
    throw new ApiError(typeof detail === 'string' && detail ? detail : GENERIC_ERROR, response.status, stepUp);
  }
  return body as T;
}

/** Calls the identity-service admin API through the portal server. */
export function portal<T>(path: string, init: {method?: string; body?: unknown; query?: Query} = {}) {
  return request<T>(withQuery(`/api/portal/${path}`, init.query), init);
}

export function authRequest<T>(path: string, init: {method?: string; body?: unknown} = {}) {
  return request<T>(`/api/auth/${path}`, init);
}

export function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : GENERIC_ERROR;
}
