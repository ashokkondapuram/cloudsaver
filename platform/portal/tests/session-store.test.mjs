import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {SessionStore} from '../lib/server/session-store.ts';

test('sessions survive reopen, rotate under a fence and revoke across replicas',()=>{
 const dir=mkdtempSync(join(tmpdir(),'portal-session-')), path=join(dir,'s.db'), key='k'.repeat(64), now=Date.now();
 const a=new SessionStore(path,key), b=new SessionStore(path,key);
 try {
  a.create('id',{credential:'sensitive-value'},now+60000,now+30000);
  assert.deepEqual(b.read('id',now,false,30000),{credential:'sensitive-value'});
  const fence=a.claimRefresh('id',now);assert.ok(fence);assert.equal(b.claimRefresh('id',now),null);
  assert.equal(b.finishRefresh('id',fence-1,{},now),false);
  assert.equal(a.finishRefresh('id',fence,{credential:'rotated'},now),true);
  const next=b.claimRefresh('id',now);assert.notEqual(next,fence);assert.equal(a.finishRefresh('id',fence,{},now),false);
  b.delete('id');assert.equal(a.read('id',now,false,30000),null);
  a.create('pending',{nonce:'one-use'},now+60000,now+60000);
  assert.deepEqual(b.take('pending',now),{nonce:'one-use'});assert.equal(a.take('pending',now),null);
  assert.equal(readFileSync(path).includes(Buffer.from('sensitive-value')),false);
 } finally {a.close();b.close();rmSync(dir,{recursive:true,force:true});}
});
test('expired, differently encrypted and replayed sessions fail closed',()=>{
 const dir=mkdtempSync(join(tmpdir(),'portal-session-')),path=join(dir,'s.db'),now=Date.now();
 const a=new SessionStore(path,'a'.repeat(64)),b=new SessionStore(path,'b'.repeat(64));
 try {a.create('id',{},now+10000,now+1000);assert.equal(a.read('id',now+1001,false,1000),null);assert.equal(b.read('id',now,false,1000),null);}
 finally {a.close();b.close();rmSync(dir,{recursive:true,force:true});}
});
