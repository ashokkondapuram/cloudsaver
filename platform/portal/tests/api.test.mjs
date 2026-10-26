import {test} from 'node:test';
import assert from 'node:assert/strict';
import {portal,ApiError,withQuery} from '../lib/api.ts';

for(const raw of ['broken','null','42','"text"'])test(`portal rejects incomplete successful payload ${raw}`,async t=>{
  t.mock.method(globalThis,'fetch',async()=>new Response(raw,{status:200}));
  await assert.rejects(portal('customers'),error=>error instanceof ApiError&&/incomplete response/.test(error.message));
});

test('uncertain portal mutation tells the operator to reconcile and never retries',async t=>{
  let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;throw new TypeError('synthetic disconnect');});
  await assert.rejects(portal('payments',{method:'POST',body:{}}),error=>error instanceof ApiError&&error.uncertain&&/Check activity/.test(error.message));assert.equal(calls,1);
});

test('unavailable mutation and forbidden requests remain different outcomes',async t=>{
  const mocked=t.mock.method(globalThis,'fetch',async()=>new Response('{"detail":"retry"}',{status:503}));
  await assert.rejects(portal('payments',{method:'POST',body:{}}),error=>error.uncertain&&/Check activity/.test(error.message));
  mocked.mock.mockImplementation(async()=>new Response('{"detail":"permission","step_up":true}',{status:403}));
  await assert.rejects(portal('payments',{method:'POST',body:{}}),error=>error.status===403&&error.stepUp&&!error.uncertain&&error.message==='permission');
});

test('204 success does not become a JSON parsing failure',async t=>{
  t.mock.method(globalThis,'fetch',async()=>new Response(null,{status:204}));assert.equal(await portal('logout',{method:'POST'}),undefined);
});

test('query encoding preserves punctuation and zero without adding missing filters',()=>{
  assert.equal(withQuery('/path',{q:'a&b',offset:0,empty:'',missing:null}),'/path?q=a%26b&offset=0');
});
