import {test} from 'node:test';
import assert from 'node:assert/strict';
import {allowsIntegrationRoute} from '../lib/proxy-contract.ts';
test('integration admission binds method and path without exposing internal routes',()=>{
 const id='11111111-1111-4111-8111-111111111111';
 for(const path of ['v1/rules/catalog/azure-compute','v1/rules/catalog/by-pillar','v1/kubernetes/grafana/connectors',`v1/kubernetes/grafana/rightsizing/jobs/${id}`])assert.equal(allowsIntegrationRoute('GET',path),true);
 assert.equal(allowsIntegrationRoute('POST',`v1/kubernetes/grafana/connectors/${id}/test`),true);
 for(const [method,path] of [['POST','v1/rules/catalog/by-pillar'],['GET','v1/kubernetes/grafana/rightsizing/run'],['GET','internal/v1/analysis/resource'],['GET','v1/kubernetes/grafana/connectors/../secrets']])assert.equal(allowsIntegrationRoute(method,path),false);
});
