import {test,expect} from './test';
import {api,ApiError,watchUnauthorized} from '../lib/api';
const original=globalThis.fetch;
test.afterEach(()=>{globalThis.fetch=original;});

test('authorization failures notify only the credential whose request was rejected',async()=>{
  let a=0,b=0;const offA=watchUnauthorized('a',()=>a++),offB=watchUnauthorized('b',()=>b++);
  try{globalThis.fetch=async()=>new Response('{"detail":"revoked"}',{status:401});
    await expect(api('/me','a')).rejects.toMatchObject({status:401});expect([a,b]).toEqual([1,0]);
    offA();await expect(api('/me','a')).rejects.toMatchObject({status:401});expect([a,b]).toEqual([1,0]);
  }finally{offA();offB();}
});

test('forbidden access preserves the active authenticated session and request reference',async()=>{
  let calls=0;const off=watchUnauthorized('valid',()=>calls++);
  try{globalThis.fetch=async()=>new Response('{"detail":"Scope denied"}',{status:403,headers:{'x-request-id':'test-reference'}});
    await expect(api('/me','valid')).rejects.toMatchObject({message:'Scope denied',status:403,requestId:'test-reference'});expect(calls).toBe(0);
  }finally{off();}
});

for(const raw of ['broken','null','42','"text"'])test(`invalid success ${raw} becomes an evidence error`,async()=>{
  globalThis.fetch=async()=>new Response(raw,{status:200});
  await expect(api('/scans','a')).rejects.toMatchObject({message:'The service returned incomplete evidence. Refresh to try again.',uncertain:false});
});

test('ambiguous mutations are never automatically retried or described as safe retries',async()=>{
  let calls=0;globalThis.fetch=async()=>{calls++;throw new TypeError('synthetic disconnect');};
  await expect(api('/change','a',{body:{version:1}})).rejects.toMatchObject({status:0,uncertain:true,message:expect.stringContaining('Check its status or activity')});
  expect(calls).toBe(1);
  globalThis.fetch=async()=>new Response('{"detail":"retry"}',{status:503});
  await expect(api('/change','a',{body:{version:1}})).rejects.toMatchObject({status:503,uncertain:true,message:expect.stringContaining('before submitting again')});
});

test('empty successful writes and caller cancellations have distinct outcomes',async()=>{
  globalThis.fetch=async()=>new Response(null,{status:204});expect(await api('/change','a',{body:{}})).toBeUndefined();
  const controller=new AbortController();controller.abort();globalThis.fetch=async()=>{throw controller.signal.reason;};
  await expect(api('/scans','a',{signal:controller.signal})).rejects.not.toBeInstanceOf(ApiError);
});

test('request cancellation works without the newer AbortSignal.any API',async()=>{
  const descriptor=Object.getOwnPropertyDescriptor(AbortSignal,'any');
  try{
    Reflect.deleteProperty(AbortSignal,'any');
    const controller=new AbortController();let observed:AbortSignal|undefined;
    globalThis.fetch=async(_input,init)=>{
      observed=init?.signal as AbortSignal;controller.abort();
      if(observed.aborted)throw observed.reason;
      throw new Error('Caller cancellation was not forwarded.');
    };
    await expect(api('/scans','a',{signal:controller.signal})).rejects.toBe(controller.signal.reason);
    expect(observed?.aborted).toBe(true);
  }finally{if(descriptor)Object.defineProperty(AbortSignal,'any',descriptor);}
});
