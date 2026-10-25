import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,subscriptionId} from './workspace-fixture';

test('human preservation release requires a reason, ticket and explicit confirmation',async({page})=>{
  await mockWorkspace(page,{human:true});const attempt='77777777-7777-4777-8777-777777777777',hold='88888888-8888-4888-8888-888888888888';let released=false,body:unknown;
  await page.route('**/api/v1/ai/governance',route=>route.fulfill({json:{policy:{status:'enforced',environment_id:'qa-company',response_retention_days:7,processors:[]},records:[{attempt_id:attempt,purpose:'assessment',expires_at:'2026-12-01T00:00:00Z',erased_at:null}],active_holds:released?[]:[{id:hold,attempt_id:attempt,hold_until:'2026-11-01T00:00:00Z',review_reference:'LEGAL-42'}],events:[],counts:{}}}));
  await page.route(`**/api/v1/ai/governance/holds/${hold}/release`,route=>{released=true;body=route.request().postDataJSON();return route.fulfill({json:{released:true}});});
  await navigate(page,'AI data governance');await expect(page.getByRole('button',{name:'Erase AI content',exact:true})).toBeDisabled();await page.getByRole('button',{name:'Release hold'}).click();
  const form=page.getByRole('form',{name:'Legal hold release review'});await expect(form.getByRole('button',{name:'Confirm hold release'})).toBeDisabled();
  await form.getByLabel('Release reason').fill('Preservation review completed');await form.getByLabel('Review ticket').fill('LEGAL-RELEASE-42');await form.getByRole('checkbox').check();await form.getByRole('button',{name:'Confirm hold release'}).click();
  await expect(page.getByRole('button',{name:'Erase AI content',exact:true})).toBeEnabled();expect(body).toEqual({release_reason:'Preservation review completed',review_ticket:'LEGAL-RELEASE-42'});
});
