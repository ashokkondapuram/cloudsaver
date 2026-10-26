import {test,expect} from './test';
import {loadResourcePages,MAX_RESOURCE_ROWS} from '../lib/resource-pages';
import {buildResourceItems,createFindings,scanId,scanTime} from './workspace-fixture';
const items=buildResourceItems(createFindings(1001));
function page(rows=items.slice(0,1000),total=1001){return {scan_id:scanId,observed_at:scanTime,total,items:rows,summary:{total,ai_status:{not_run:total},ai_risk:{none:total},decision:{none:total},review_priority:{high:total}}};}

test('inventory reads subsequent pages and includes the last resource exactly once',async()=>{
  const paths:string[]=[];
  const result=await loadResourcePages(async path=>{paths.push(path);return path.includes('offset=1000')?page(items.slice(1000)):page();},scanId);
  expect(paths).toHaveLength(2);expect(result.items).toHaveLength(1001);expect(result.items.at(-1)?.resource_name).toBe('archive-data-1001');
});

test('empty inventory is complete rather than an invented cost estimate',async()=>{
  const result=await loadResourcePages(async()=>page([],0),scanId);expect(result.total).toBe(0);expect(result.items).toEqual([]);
});

for(const reason of ['foreign scan','changed total','changed observation','duplicate','empty tail','missing summary','invalid row','over limit'])test(`incomplete inventory rejects ${reason} without returning a partial result`,async()=>{
  let calls=0;
  await expect(loadResourcePages(async()=>{
    calls++;const response:Record<string,unknown>=calls===1?page():page(items.slice(1000));
    if(calls===2){
      if(reason==='foreign scan')response.scan_id='other';
      if(reason==='changed total'){response.total=1002;response.summary={...(response.summary as object),total:1002};}
      if(reason==='changed observation')response.observed_at='2026-10-23T00:00:00Z';
      if(reason==='duplicate')response.items=[items[0]];
      if(reason==='empty tail')response.items=[];
      if(reason==='missing summary')delete response.summary;
      if(reason==='invalid row')response.items=[{...items[1000],ai:null}];
      if(reason==='over limit'){response.total=MAX_RESOURCE_ROWS+1;response.summary={...(response.summary as object),total:MAX_RESOURCE_ROWS+1};}
    }
    return response;
  },scanId)).rejects.toThrow('Resource evidence is incomplete');
  expect(calls).toBe(2);
});

test('cancelled inventory does not make another source request',async()=>{
  const controller=new AbortController();let calls=0;
  await expect(loadResourcePages(async()=>{calls++;controller.abort();return page();},scanId,controller.signal)).rejects.toThrow();
  expect(calls).toBe(1);
});

import {readBatchPage} from '../lib/resource-pages';
const batch={id:'44444444-4444-4444-8444-444444444444',scan_id:scanId,status:'running',total:2,counts:{queued:1,running:1,completed:0,failed:0,skipped:0,uncertain:0,cancelled:0}};
test('batch progress preserves explicit zero and requires complete counters',()=>{
  expect(readBatchPage({items:[batch]},scanId)).toEqual(batch);
  expect(readBatchPage({items:[]},scanId)).toBeNull();
  for(const value of [{...batch,counts:{}},{...batch,scan_id:'foreign'},{...batch,total:3},{...batch,total:NaN},{...batch,counts:{...batch.counts,completed:-1}}])expect(()=>readBatchPage({items:[value]},scanId)).toThrow('status is unavailable');
});
