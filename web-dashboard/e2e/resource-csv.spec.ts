import {test,expect} from '@playwright/test';
import {resourceCsv} from '../lib/resource-csv';
import type {ResourceRow} from '../lib/resources';
import {mockWorkspace,navigate} from './workspace-fixture';

test('resource CSV preserves zero and unknowns while neutralizing formulas and quoting text',()=>{
  const row:ResourceRow={resource_key:'a'.repeat(64),resource_id:'fixture',resource_type:'disk',resource_group:'fixture',scope_id:'scope',service_category:'storage',finding_count:2,review_priority:'evidence_required',disposition:'requires_review',protected_reasons:[],risk_level:'unknown',risk_check_codes:[],evidence_gap_codes:[],evidence_coverage:{observed:0,total:1},evidence_digest:'b'.repeat(64),provider:'azure',resource_name:'  =HYPERLINK("bad")',rule_ids:['A','B'],pillars:{cost:'unknown'},
    retail_estimate_usd:0,billed_cost_usd:null,ai:{status:'not_run',risk_level:null,summary:'line1\nline2',actions:[],assessment_id:null,created_at:null,reason:null},decision:null};
  const csv=resourceCsv([row]);
  expect(csv).toContain('"\'  =HYPERLINK(""bad"")"');
  expect(csv).toContain('"A;B"');
  expect(csv).toContain('"line1\nline2"');
  expect(csv).toContain('"unknown"');
  expect(csv).toContain('"","","0"');
  expect(csv).not.toContain('"null"');
  expect(csv).not.toContain('"undefined"');
});

test('resource CSV follows active quick-view filters instead of exporting hidden rows',async({page})=>{
  await mockWorkspace(page,{protected:true});
  let serverExports=0;
  await page.route('**/api/v1/scans/*/resources/export*',async route=>{serverExports++;await route.fulfill({status:500});});
  await navigate(page,'Resources');
  await page.getByRole('group',{name:'Evidence quick views'}).getByRole('button',{name:'Protected intent',exact:true}).click();
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(1);
  const downloaded=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export CSV',exact:true}).click();
  const stream=await (await downloaded).createReadStream();
  const chunks:Buffer[]=[];for await(const chunk of stream!)chunks.push(Buffer.from(chunk));
  const csv=Buffer.concat(chunks).toString('utf8');
  expect(csv).toContain('archive-data-01');
  expect(csv).not.toContain('archive-data-05');
  expect(csv.trim().split('\r\n')).toHaveLength(2);
  expect(serverExports).toBe(0);
});
