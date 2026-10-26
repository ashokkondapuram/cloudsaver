export class ApiError extends Error {
  constructor(message: string, public status: number, public uncertain = false, public requestId: string | null = null) {super(message);}
}

// Bind invalidation to the exact active credential. A late response from a
// disconnected workspace must never terminate the newly connected session.
const unauthorized = new Map<string, Set<() => void>>();
export function watchUnauthorized(token: string, callback: () => void) {
  const callbacks=unauthorized.get(token)||new Set<()=>void>();
  callbacks.add(callback);unauthorized.set(token,callbacks);
  return ()=>{callbacks.delete(callback);if(!callbacks.size)unauthorized.delete(token);};
}
const unknownOutcome='The request outcome could not be confirmed. Check its status or activity before submitting again.';

export async function api<T>(path: string, token: string, options: {body?: unknown; rawBody?: string; signal?: AbortSignal; method?: 'GET' | 'POST' | 'PUT' | 'PATCH'} = {}): Promise<T> {
  const hasBody=options.body!==undefined||options.rawBody!==undefined;
  const method=options.method??(hasBody?'POST':'GET'), mutation=method!=='GET';
  const controller=new AbortController();
  const forwardAbort=()=>controller.abort(options.signal?.reason);
  options.signal?.addEventListener('abort',forwardAbort,{once:true});
  if(options.signal?.aborted)forwardAbort();
  const timeout=setTimeout(()=>controller.abort(),125_000);
  const signal=controller.signal;
  let response:Response, raw:unknown;
  try {
    response=await fetch('/api/v1'+path,{
      method,headers:{Authorization:'Bearer '+token,...(hasBody?{'Content-Type':'application/json'}:{})},
      body:options.rawBody??(options.body===undefined?undefined:JSON.stringify(options.body)),cache:'no-store',signal,
    });
    // Revoke the session before waiting for any untrusted error response body.
    if(response.status===401) for(const callback of [...(unauthorized.get(token)||[])]) callback();
    if(response.status===204)return undefined as T;
    const text=await response.text();
    try {raw=JSON.parse(text);} catch {raw=undefined;}
  } catch(cause) {
    if(options.signal?.aborted)throw cause;
    throw new ApiError(mutation?unknownOutcome:'The service could not be reached. Check your connection and refresh to try again.',0,mutation);
  }finally{clearTimeout(timeout);options.signal?.removeEventListener('abort',forwardAbort);}
  if(!response.ok){
    let message=response.status===401?'Your session could not be verified. Connect again to continue.':`Request could not be completed (${response.status}).`;
    if(raw&&typeof raw==='object'&&'detail' in raw&&typeof raw.detail==='string')message=raw.detail;
    const uncertain=mutation&&response.status>=500;
    throw new ApiError(uncertain?unknownOutcome:message,response.status,uncertain,response.headers.get('x-request-id'));
  }
  if(raw===undefined||raw===null||typeof raw!=='object')throw new ApiError(mutation?unknownOutcome:'The service returned incomplete evidence. Refresh to try again.',response.status,mutation,response.headers.get('x-request-id'));
  return raw as T;
}
