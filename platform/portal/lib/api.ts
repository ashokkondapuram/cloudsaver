'use client';

export const GENERIC_ERROR = 'Something went wrong. If the issue persists, contact Support.';

export class ApiError extends Error {
  readonly status:number;
  readonly stepUp:boolean;
  readonly uncertain:boolean;
  constructor(message:string,status:number,stepUp=false,uncertain=false){
    super(message);this.status=status;this.stepUp=stepUp;this.uncertain=uncertain;
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
  const mutation=(init.method||'GET')!=='GET';
  const uncertain='The request outcome could not be confirmed. Check activity before submitting again.';
  let response: Response, text: string;
  try {
    response = await fetch(url, {
      method: init.method || 'GET',
      headers: init.body === undefined ? {Accept: 'application/json'} : {Accept: 'application/json', 'Content-Type': 'application/json'},
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: 'same-origin',
      cache: 'no-store',
      signal: AbortSignal.timeout(30_000),
    });
    if (response.headers.get('X-Portal-Session') === 'ended' && typeof window !== 'undefined') {
      window.location.assign(`/sign-in?error=session_ended&return_to=${encodeURIComponent(window.location.pathname)}`);
    }
    if(response.status===204)return undefined as T;
    text=await response.text();
  } catch {
    throw new ApiError(mutation?uncertain:"We couldn't reach the portal. Check your connection and try again.", 0, false, mutation);
  }
  let body: unknown = null;
  try {body = text ? JSON.parse(text) : null;} catch {body = null;}
  if (!response.ok) {
    const detail = (body as {detail?: unknown} | null)?.detail;
    const stepUp = (body as {step_up?: unknown} | null)?.step_up === true;
    throw new ApiError(mutation&&response.status>=500?uncertain:typeof detail === 'string' && detail ? detail : GENERIC_ERROR, response.status, stepUp, mutation&&response.status>=500);
  }
  const path=url.split('?')[0];
  const paged=/^\/api\/portal\/(?:customers|workspaces|plans|billing\/customers|audit|failures|plan-change-requests|knowledge\/publications|customers\/[^/]+\/(?:subscriptions|payments)|workspaces\/[^/]+\/keys)$/.test(path);
  const incompletePage=!mutation&&paged&&(!body||typeof body!=='object'||!Array.isArray((body as {items?:unknown}).items)||('next_cursor' in body&&((body as {next_cursor?:unknown}).next_cursor!==null&&typeof (body as {next_cursor?:unknown}).next_cursor!=='string')));
  if(body===null||typeof body!=='object'||incompletePage)throw new ApiError(mutation?uncertain:'The portal returned an incomplete response. Refresh to try again.', response.status, false, mutation);
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
