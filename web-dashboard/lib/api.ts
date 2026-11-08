export class ApiError extends Error {
  status: number;
  uncertain: boolean;
  requestId: string | null;
  constructor(message: string, status: number, uncertain = false, requestId: string | null = null) {super(message);this.status=status;this.uncertain=uncertain;this.requestId=requestId;}
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

/** Validate critical route envelopes before components consume their fields. */
export function validateApiPayload(path: string, value: unknown) {
  const object=(v:unknown):v is Record<string,unknown> => !!v && typeof v==='object' && !Array.isArray(v);
  // Node count is bounded by the byte budget already enforced on the response body
  // (see api()), so no separate flat node cap is needed here.
  const pending:unknown[]=[value];
  while(pending.length){
    const next=pending.pop();
    if(typeof next==='number'&&!Number.isFinite(next))throw new Error('Invalid numeric evidence');
    if(Array.isArray(next)){if(next.length>100_000)throw new Error('Response exceeds collection budget');for(const item of next)pending.push(item);}
    else if(object(next))pending.push(...Object.values(next));
  }
  const route=path.split('?')[0];
  if(route==='/scans') {
    if(!Array.isArray(value)||value.some(v=>!object(v)||typeof v.scan_id!=='string'||typeof v.status!=='string'||!Array.isArray(v.findings)))throw new Error('Invalid scan history');
  } else if(route==='/me') {
    if(!object(value)||typeof value.tenant_id!=='string'||typeof value.name!=='string'||!Array.isArray(value.roles)||!Array.isArray(value.subscription_ids))throw new Error('Invalid workspace');
  } else if(object(value) && 'items' in value) {
    if(!Array.isArray(value.items))throw new Error('Invalid list envelope');
    if('next_cursor' in value && value.next_cursor!==null && typeof value.next_cursor!=='string')throw new Error('Invalid pagination cursor');
  }
}

export async function api<T>(path: string, token: string, options: {body?: unknown; rawBody?: string; signal?: AbortSignal; method?: 'GET' | 'POST' | 'PUT' | 'PATCH'; idempotencyKey?: string; version?: number; timeoutMs?: number; decode?: (value:unknown)=>T} = {}): Promise<T> {
  const hasBody=options.body!==undefined||options.rawBody!==undefined;
  const method=options.method??(hasBody?'POST':'GET'), mutation=method!=='GET';
  const controller=new AbortController();
  const forwardAbort=()=>controller.abort(options.signal?.reason);
  options.signal?.addEventListener('abort',forwardAbort,{once:true});
  if(options.signal?.aborted)forwardAbort();
  const timeout=setTimeout(()=>controller.abort(),options.timeoutMs ?? 125_000);
  const signal=controller.signal;
  let response:Response, raw:unknown;
  try {
    response=await fetch('/api/v1'+path,{
      method,headers:{Authorization:'Bearer '+token,...(hasBody?{'Content-Type':'application/json'}:{}),...(options.idempotencyKey?{'Idempotency-Key':options.idempotencyKey}:{}),...(options.version?{'If-Match':`"${options.version}"`}:{})},
      body:options.rawBody??(options.body===undefined?undefined:JSON.stringify(options.body)),cache:'no-store',signal,
    });
    // Revoke the session before waiting for any untrusted error response body.
    if(response.status===401) for(const callback of [...(unauthorized.get(token)||[])]) callback();
    if(response.status===204)return undefined as T;
    const reader=response.body?.getReader();let size=0;const decoder=new TextDecoder();let text='';
    if(reader){while(true){const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.byteLength;
      if(size>20_000_000){await reader.cancel();throw new Error('Response exceeds byte budget');}
      text+=decoder.decode(chunk.value,{stream:true});}text+=decoder.decode();}
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
  try {
    validateApiPayload(path,raw);
    return options.decode ? options.decode(raw) : raw as T;
  } catch {
    throw new ApiError(mutation?unknownOutcome:'The service returned incomplete evidence. Refresh to try again.',response.status,mutation,response.headers.get('x-request-id'));
  }
}
