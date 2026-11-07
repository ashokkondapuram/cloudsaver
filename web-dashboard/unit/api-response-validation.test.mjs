import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateApiPayload} from '../lib/api.ts';
test('critical response envelopes reject incomplete success bodies',()=>{
 for(const [path,value] of [['/scans',{}],['/scans',[{}]],['/me',{}],['/resources',{items:null}],['/resources',{items:[],next_cursor:42}]])assert.throws(()=>validateApiPayload(path,value));
 validateApiPayload('/scans',[]);
 validateApiPayload('/resources',{items:[],next_cursor:null});
 validateApiPayload('/me',{tenant_id:'t',name:'workspace',roles:[],subscription_ids:[]});
});
test('nonfinite metrics and oversized nested collections reject',()=>{
 assert.throws(()=>validateApiPayload('/metrics',{series:[{value:Infinity}]}));
 assert.throws(()=>validateApiPayload('/metrics',{series:Array(100001).fill(null)}));
 validateApiPayload('/metrics',{series:[{value:0},{value:null}]});
});
