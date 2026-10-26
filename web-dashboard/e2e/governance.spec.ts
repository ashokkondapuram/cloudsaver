import {test,expect,type Page} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,scanTime,subscriptionId} from './workspace-fixture';

const findingId='77777777-7777-4777-8777-777777777777',riskId='88888888-8888-4888-8888-888888888888',exceptionId='99999999-9999-4999-8999-999999999999';
const owner='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',business='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',resourceId=`/subscriptions/${subscriptionId}/resourceGroups/qa/providers/Microsoft.Storage/storageAccounts/customer`;
async function setup(page:Page,options:{roles?:string[];human?:boolean;state?:string}={}){
 await mockWorkspace(page,{role:'Viewer',human:options.human??true});const mutations:{path:string;body:any}[]=[];
 const context={application:'payments',environment:'production',classification:'customer_data',technical_owner:owner,business_owner:business,rationale:'Application owner reviewed the production customer-data classification.'};
 const policy={id:'server-read-only-policy-id',control_key:'AZ-STORAGE-PUBLIC-BLOB-ACCESS',version:1,owner:'verifier',mandatory_obligation:false,risk_appetite:6,maximum_exception_days:7,rationale:'TEST FIXTURE: reviewed discretionary organizational policy.',mappings:[]};
 const assessment={result:'fail',reason:'ACCOUNT_PERMITS_PUBLIC_BLOB_ACCESS',state_digest:'a'.repeat(64),scan_id:scanId,observed_at:scanTime,configuration:{allow_blob_public_access:true},limitation:'Account permission is not proof that a container is public or that customer data was accessed.'};
 let finding:any={id:findingId,state:options.state||'proposed',version:3,created_at:scanTime,updated_at:scanTime,payload:{resource_name:'customer',resource_id:resourceId,provider:'azure',scope_id:subscriptionId,context,control:policy,original_assessment:assessment,assessment,risk_id:riskId,severity:'critical',due_date:'2026-10-26',plan:{digest:'b'.repeat(64),change_reference:'CHG-42',steps:['Disable account public blob access for the exact storage account.'],dependency_checks:['Confirm authenticated application dependency access.'],validation_steps:['Re-read configuration and test legitimate authenticated application access.'],rollback_plan:'Any rollback requires a separately reviewed and approved change.',desired_configuration:{allow_blob_public_access:false}},approval:null,implementation:null,verification:null},events:[],evidence:[],assessment_fresh:true};
 let exception:any={id:exceptionId,state:'reviewed',version:2,payload:{finding_id:findingId,risk_id:riskId,justification:'Migration requires a reviewed short transition window.',rejected_alternatives:'Immediate shutdown was rejected after continuity review.',compensating_controls:'Reviewed network filtering and monitored access.',remediation_plan:'Complete migration, then disable public access.',start:'2026-10-25T00:00:00Z',end:'2026-10-27T00:00:00Z',review_at:'2026-10-26T00:00:00Z',review_trigger:'Review on any network or application change.',requested_by:owner,review:{subject_id:'security',note:'Reviewed compensation.'},approval:null}};
 await page.route(`**/api/v1/scans/${scanId}/resources?**`,route=>route.fulfill({json:{items:[{resource_id:resourceId,resource_name:'customer',resource_type:'Microsoft.Storage/storageAccounts',provider:'azure'}]}}));
 await page.route('**/api/v1/governance/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname.replace('/api/v1/governance',''),body=req.method()==='GET'?null:req.postDataJSON();if(body)mutations.push({path,body});let response:any;
  if(path==='/capabilities')response={roles:options.roles||['Auditor'],subject_id:options.roles?.includes('ResourceOwner')?owner:options.roles?.includes('BusinessRiskOwner')?business:'reviewer',human:options.human??true,manage_access:false,readable:true,automatic_execution:false};
  else if(path==='/controls')response={policy};
  else if(path==='/directory')response={items:[{subject_id:owner,alias:'platform-owner',roles:['ResourceOwner']},{subject_id:business,alias:'business-owner',roles:['BusinessRiskOwner']},{subject_id:'verifier',alias:'control-owner',roles:['ComplianceReviewer']}]};
  else if(path==='/findings')response={items:[finding]};
  else if(path==='/risks')response={items:[{id:riskId,state:'active',version:1,payload:{statement:'Potential disclosure of customer data through public storage configuration.',treatment_plan:'Apply the reviewed private-access configuration and verify legitimate access.',business_owner:business,finding_ids:[findingId],inherent_score:20,residual_score:4,material:true,review_date:'2026-11-20'}}]};
  else if(path==='/exceptions')response={items:[exception]};
  else if(path==='/summary')response={open_material_risks:1,overdue_findings:0,expiring_exceptions:1,unknown_assessments:1,stale_evidence:0,unassigned_resources:0,assessment_results:{pass:0,fail:1,unknown:1,not_applicable:0},monitor:{checked_at:scanTime,findings_checked:1,changed:0},warning:'Technical assessments are not organizational compliance.',compliance_score:null};
  else if(path===`/findings/${findingId}`)response=finding;
  else if(path===`/findings/${findingId}/actions`){finding={...finding,state:body.action==='approve'?'approved':finding.state,version:finding.version+1};response=finding;}
  else if(path==='/assessments'){finding={...finding,state:'triage',version:1,payload:{...finding.payload,risk_id:null,plan:null}};response={assessment,finding};}
  else if(path===`/exceptions/${exceptionId}/actions`){exception={...exception,state:'approved',version:3,payload:{...exception.payload,approval:{subject_id:business,authority_reference:'RISK-AUTH-42'}}};response=exception;}
  else if(path===`/findings/${findingId}/export`)response={format:'cloudsaver-governance-audit-v1',technical_only:true,content:{finding},manifest:{finding:'c'.repeat(64)}};
  else if(path==='/monitor')response={checked_at:scanTime,findings_checked:1,changed:0,external_notifications_sent:0,automatic_execution:false};
  else throw new Error('Unmocked governance path '+path);
  await route.fulfill({json:response});
 });
 await navigate(page,'Risk & compliance');return mutations;
}

test('auditor mobile dashboard preserves uncertainty and seven accessible workflow views',async({page})=>{
 await page.setViewportSize({width:390,height:844});const mutations=await setup(page);await expect(page.getByRole('heading',{name:'Risk & compliance',exact:true})).toBeVisible();
 const tabs=page.getByRole('tablist',{name:'Risk and compliance workflows'});await expect(tabs.getByRole('tab')).toHaveCount(7);await tabs.getByRole('tab',{name:'Risk register',exact:true}).focus();await page.keyboard.press('End');await expect(tabs.getByRole('tab',{name:'Audit exports',exact:true})).toBeFocused();
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Download audit package',exact:true}).click();expect((await download).suggestedFilename()).toBe(`cloudsaver-governance-${findingId}.json`);
 await tabs.getByRole('tab',{name:'Evidence',exact:true}).click();await expect(page.getByText(/Configuration evidence cannot determine historical data exposure/)).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);expect(mutations).toEqual([]);
});

test('a change approver explicitly reviews the exact plan and cannot close a proposed issue',async({page})=>{
 const mutations=await setup(page,{roles:['ChangeApprover']});await page.getByRole('tab',{name:'Approvals',exact:true}).click();await page.getByRole('button',{name:'Review finding',exact:true}).click();const drawer=page.getByRole('dialog',{name:'Governance finding review'});
 await expect(drawer.getByRole('heading',{name:'Exact reviewed change plan'})).toBeVisible();await expect(drawer.getByRole('button',{name:'Approve verified closure'})).toHaveCount(0);const approve=drawer.getByRole('button',{name:'Approve bound change plan',exact:true});await expect(approve).toBeDisabled();
 await drawer.getByLabel('Decision / investigation note',{exact:true}).fill('Reviewed the exact target, dependencies and rollback.');await drawer.getByLabel('I reviewed the exact resource, target configuration, dependencies, validation and rollback.').check();await approve.click();
 await expect(drawer.getByText('Approved · revision 4',{exact:true})).toBeVisible();expect(mutations[0].body.action).toBe('approve');expect(mutations[0].body.version).toBe(3);
 const audit=await new AxeBuilder({page}).include('dialog[open]').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('security analyst confirms classification and named owners before creating an issue',async({page})=>{
 const mutations=await setup(page,{roles:['SecurityAnalyst']});await page.getByRole('tab',{name:'Findings',exact:true}).click();await page.getByText('Assess an observed storage account',{exact:true}).click();
 await page.getByRole('combobox',{name:'Storage account from selected scan',exact:true}).selectOption(resourceId);await page.getByLabel('Application',{exact:true}).fill('payments');await page.getByRole('combobox',{name:'Environment',exact:true}).selectOption('production');await page.getByRole('combobox',{name:'Data classification',exact:true}).selectOption('customer_data');await page.getByRole('combobox',{name:'Technical owner',exact:true}).selectOption(owner);await page.getByRole('combobox',{name:'Business risk owner',exact:true}).selectOption(business);await page.getByLabel('Business-context confirmation',{exact:true}).fill('Application owner confirmed the customer-data context.');await page.getByRole('button',{name:'Evaluate technical control',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'Governance finding review'})).toBeVisible();expect(mutations[0].body.context.technical_owner).toBe(owner);expect(mutations[0].body.context.classification).toBe('customer_data');expect(mutations[0].body).not.toHaveProperty('compliant');
});

test('accepted-risk decision remains separate from failed technical control',async({page})=>{
 const mutations=await setup(page,{roles:['BusinessRiskOwner']});await page.getByRole('tab',{name:'Exceptions',exact:true}).click();await page.getByLabel('Exception decision note',{exact:true}).fill('Authorized within documented senior risk delegation.');await page.getByRole('button',{name:'Authorize time-limited risk',exact:true}).click();await expect(page.getByText(/Accepted by business-owner/)).toBeVisible();expect(mutations[0].body.action).toBe('approve');await page.getByRole('tab',{name:'Evidence',exact:true}).click();await expect(page.locator('.gov-assessment-counts .gov-fail')).toHaveText('Fail');
});

test('keys and automation cannot exercise human approval controls',async({page})=>{
 const mutations=await setup(page,{roles:['ChangeApprover'],human:false});await page.getByRole('tab',{name:'Approvals',exact:true}).click();await page.getByRole('button',{name:'Review finding',exact:true}).click();const drawer=page.getByRole('dialog',{name:'Governance finding review'});await expect(drawer.getByRole('button',{name:'Approve bound change plan',exact:true})).toBeDisabled();expect(mutations).toEqual([]);
});

test('control policy revision submits reviewed inputs without read-only server metadata',async({page})=>{
 const mutations=await setup(page,{roles:['ComplianceReviewer']});await page.getByRole('tab',{name:'Controls',exact:true}).click();await page.getByText('Review a new control-policy version',{exact:true}).click();await page.getByRole('textbox',{name:'Policy applicability and risk-appetite rationale',exact:true}).fill('The compliance reviewer confirmed this organizational policy revision.');await page.getByRole('button',{name:'Publish reviewed policy version',exact:true}).click();await expect(page.getByText(/New immutable control policy reviewed/)).toBeVisible();const submitted=mutations.find(m=>m.path==='/controls')!;expect(submitted.body).not.toHaveProperty('id');expect(submitted.body).not.toHaveProperty('control_key');expect(submitted.body.version).toBe(1);
});
