import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {allowsBrowserRoute} from '../lib/generated/browser-routes.ts';
const contract=JSON.parse(readFileSync(new URL('../lib/browser-operations.json',import.meta.url),'utf8'));
const id='11111111-1111-4111-8111-111111111111';
function example(path){return path.slice(5).replace(/\{([^}]+)\}/g,(_,name)=>name==='key'||name==='resource_key'?'a'.repeat(64):name==='key_id'?'Ab1234567890':name==='service'||name==='service_name'?'virtual-machines':name==='decision'?'hold':id);}

test('every reviewed operation has matching method/path admission',()=>{
 for(const row of contract.operations){
  assert.equal(allowsBrowserRoute(row.method,example(row.path)),row.browser,`${row.method} ${row.path}`);
  assert.equal(allowsBrowserRoute('TRACE',example(row.path)),false);
 }
});
test('integration routes remain reachable and mutation methods remain distinct',()=>{
 assert.equal(allowsBrowserRoute('GET','v1/rules/catalog/by-pillar'),true);
 assert.equal(allowsBrowserRoute('POST',`v1/kubernetes/grafana/connectors/${id}/test`),true);
 assert.equal(allowsBrowserRoute('POST','v1/rules/catalog/by-pillar'),false);
 assert.equal(allowsBrowserRoute('GET','v1/kubernetes/grafana/rightsizing/run'),false);
 assert.equal(allowsBrowserRoute('GET','v1/analytics'),true);
});
test('internal, unreviewed, malformed and doubly encoded paths are refused',()=>{
 for(const path of ['internal/v1/analysis/resource','v1/new-unreviewed-operation','v1/me\n','v1/me?x=1','v1//me','v1/kubernetes/grafana/connectors/../secrets','v1/services/%252fsecrets','v1/services/invalid\\path'])assert.equal(allowsBrowserRoute('GET',path),false,path);
 assert.equal(allowsBrowserRoute('GET','v1/resources/not-a-digest/history'),false);
 assert.equal(allowsBrowserRoute('GET','v1/scans/not-a-uuid/resources'),false);
});
