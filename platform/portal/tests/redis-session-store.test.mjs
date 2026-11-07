import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {RedisSessionStore} from '../lib/server/redis-session-store.ts';

test('shared Redis sessions fence refresh, consume state once and revoke across clients', {skip:!process.env.REDIS_SESSION_TEST_URL},async()=>{
 const secret='test-only-'.repeat(8), id='acceptance:'+randomUUID(), now=Date.now();
 const a=await RedisSessionStore.connect(process.env.REDIS_SESSION_TEST_URL,secret), b=await RedisSessionStore.connect(process.env.REDIS_SESSION_TEST_URL,secret);
 try {
  await a.create(id,{credential:'synthetic-credential'},now+60000,now+30000);
  assert.deepEqual(await b.read(id,now,false,30000),{credential:'synthetic-credential'});
  const claims=await Promise.all([a.claimRefresh(id,now),b.claimRefresh(id,now)]);
  assert.equal(claims.filter(v=>v!==null).length,1);const fence=claims.find(v=>v!==null);
  assert.equal(await b.finishRefresh(id,fence+1,{},now),false);
  assert.equal(await a.finishRefresh(id,fence,{credential:'rotated'},now),true);
  const newer=await b.claimRefresh(id,now);assert.notEqual(newer,fence);
  assert.equal(await a.finishRefresh(id,fence,{},now),false);
  const values=await Promise.all([a.take(id,now),b.take(id,now)]);
  assert.equal(values.filter(v=>v!==null).length,1);
  assert.equal(await a.read(id,now,false,30000),null);
  assert.equal(await a.finishRefresh(id,newer,{},now),false);
  await a.create(id,{},Date.now()+60000,Date.now()+30000);
  await b.delete(id);assert.equal(await a.read(id,now,false,30000),null);
 } finally {await a.delete(id);a.close();b.close();}
});

test('adapter encrypts the payload before sending it to Redis',async()=>{
 const calls=[];const store=new RedisSessionStore(async args=>{calls.push(args);return 1;},'s'.repeat(64));
 await store.create('test', {credential:'never-on-the-wire-in-plaintext'},Date.now()+10000,Date.now()+10000);
 assert.equal(JSON.stringify(calls).includes('never-on-the-wire-in-plaintext'),false);
 assert.equal(calls[0][0],'EVAL');store.close();
});

test('expired idle state is unavailable even with a spoofed client timestamp',{skip:!process.env.REDIS_SESSION_TEST_URL},async()=>{
 const id='acceptance:'+randomUUID(),store=await RedisSessionStore.connect(process.env.REDIS_SESSION_TEST_URL,'t'.repeat(64));
 try {
  await store.create(id,{},Date.now()+60000,Date.now()+200);
  await new Promise(resolve=>setTimeout(resolve,300));
  assert.equal(await store.read(id,0,true,30000),null);
  assert.equal(await store.claimRefresh(id,0),null);
 } finally {await store.delete(id);store.close();}
});

test('invalid encryption configuration rejects before connecting',async()=>{
 await assert.rejects(RedisSessionStore.connect('redis://127.0.0.1:1','short'),/encryption secret/);
});
