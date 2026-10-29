import {test} from 'node:test';
import assert from 'node:assert/strict';
import {GET as portalLive} from '../app/health/live/route.ts';
import {GET as portalReady} from '../app/health/ready/route.ts';
import {GET as dashboardLive} from '../../../web-dashboard/app/health/live/route.ts';
import {GET as dashboardReady} from '../../../web-dashboard/app/health/ready/route.ts';

for (const [name,live,ready] of [['portal',portalLive,portalReady],['dashboard',dashboardLive,dashboardReady]]) {
  test(`${name} health keeps liveness up when its dependency is unavailable`,async t=>{
    const request=t.mock.method(globalThis,'fetch',async()=>{throw new Error('private endpoint');});
    assert.equal((await live()).status,200);
    assert.equal(request.mock.calls.length,0);
    const failed=await ready();
    assert.equal(failed.status,503);
    assert.deepEqual(await failed.json(),{status:'unavailable'});
    request.mock.mockImplementation(async(_url,options)=>{
      assert.equal(options.redirect,'error');
      assert.equal(options.cache,'no-store');
      assert.ok(options.signal);
      assert.equal(options.headers,undefined);
      return new Response(null,{status:200});
    });
    assert.equal((await ready()).status,200);
    request.mock.mockImplementation(async()=>new Response(null,{status:302,headers:{location:'https://other.example'}}));
    assert.equal((await ready()).status,503);
  });
}
