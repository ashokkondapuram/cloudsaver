'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect, useMemo, useState} from 'react';
import {Activity, BrainCircuit, ArrowRight, Bell, Blocks, Check, CheckCircle2, ChevronRight, Cloud, CreditCard, Database, ExternalLink, FileCode2, GitBranch, GitPullRequest, History, KeyRound, Layers3, LockKeyhole, MinusCircle, Plus, Settings2, ShieldCheck, Tags, Target, Wallet} from 'lucide-react';
import {api} from '../lib/api';
import {dateTime, money, observedTags, providerNames, providerOf, scopeOf} from '../lib/finops';
import {CONTACT_ACCOUNT_MANAGER, billingStateLabels, frequencyNames, manageBillingUrl, planDate} from '../lib/plan';
import type {Entitlements, PlanOption, Reliability} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {useScopedFindings} from './Overview';
import {GitOpsPanel, PlanPolicyPanel} from './GitOpsPanel';
import {ReliabilityPanel} from './ReliabilityPanel';
import {ServiceAnalysis} from './ServiceAnalysis';
import {BillingEvidencePanel,AIAssessmentHistory} from './EnterpriseEvidence';
import {EmptyState, Loading, Notice, ProviderBadge, SectionTitle} from './ui/shared';
import {CloudScopesEditor, IdentityOnboardingPanel, ScheduleAlertsEditor} from './settings/WorkspaceSettings';

export function Allocation() {
  const {setScope} = useWorkspace();
  const findings = useScopedFindings();
  const router = useRouter();
  const [query,setQuery] = useState('');
  const groups = useMemo(() => {
    const map = new Map<string,{provider:string;scope:string;count:number;priced:number;amount:number;tags:number}>();
    for (const f of findings) {
      const key = JSON.stringify([providerOf(f),scopeOf(f)]);
      const group = map.get(key) || {provider:providerOf(f),scope:scopeOf(f),count:0,priced:0,amount:0,tags:0};
      group.count++; if(f.estimated_monthly_waste_usd !== null) {group.priced++;group.amount+=f.estimated_monthly_waste_usd;}
      if(Object.keys(observedTags(f)).length)group.tags++;
      map.set(key,group);
    }
    return [...map.values()].sort((a,b)=>b.count-a.count);
  }, [findings]);
  const priced = findings.filter(f => f.estimated_monthly_waste_usd!==null);
  const tagged = findings.filter(f => Object.keys(observedTags(f)).length);
  return <><section className="allocation-metrics"><article className="metric-card"><div className="metric-label">Observed accounts / scopes<Layers3 size={17}/></div><strong>{groups.length}</strong><div className="metric-footnote">With findings in this view</div></article><article className="metric-card"><div className="metric-label">Priced portion<Wallet size={17}/></div><strong>{priced.length ? money(priced.reduce((sum,f)=>sum+(f.estimated_monthly_waste_usd||0),0)) : 'Not estimated'}</strong><div className="metric-footnote">{priced.length} of {findings.length} findings · excludes unknown costs</div></article><article className="metric-card"><div className="metric-label">Tag evidence coverage<Tags size={17}/></div><strong>{findings.length ? `${Math.round(tagged.length/findings.length*100)}%` : '—'}</strong><div className="metric-footnote">{tagged.length} observations contain tags or labels</div></article></section>
    <div className="allocation-banner"><span><Wallet size={23}/></span><div><h3>A clear view of the evidence you have.</h3><p>This view groups resource findings by provider and account. Billing-based chargeback, showback, and unit economics require a connected billing allocation feed.</p></div></div>
    <section className="panel"><SectionTitle title="Account & scope breakdown" action={<label className="inline-search"><span className="sr-only">Search scopes</span><input type="search" aria-label="Search scopes" placeholder="Search account or scope…" value={query} onChange={e=>setQuery(e.target.value)}/></label>}>Resource signals and retail estimates from the selected snapshot</SectionTitle>{groups.length ? <div className="summary-table-scroll"><table className="summary-table"><thead><tr><th>Account / scope</th><th>Provider</th><th>Findings</th><th>Pricing coverage</th><th>Known retail portion</th><th><span className="sr-only">Explore</span></th></tr></thead><tbody>{groups.filter(group=>`${group.scope} ${providerNames[group.provider]}`.toLowerCase().includes(query.toLowerCase())).map(group=><tr key={group.provider+group.scope}><td><code>{group.scope}</code></td><td><ProviderBadge provider={group.provider}/></td><td>{group.count}</td><td><div className="coverage-cell"><span>{group.priced}/{group.count}</span><i><b style={{width:`${group.priced/group.count*100}%`}}/></i></div></td><td>{group.priced ? money(group.amount) : 'Not estimated'}</td><td><button className="icon-button" aria-label={`Explore scope ${group.scope}`} onClick={()=>{setScope([group.scope]);router.push(`/findings?provider=${encodeURIComponent(group.provider)}`);}}><ArrowRight size={16}/></button></td></tr>)}</tbody></table></div> : <EmptyState icon={Layers3} title="No scoped findings yet">A completed resource scan will populate your account breakdown.</EmptyState>}</section>
    <BillingEvidencePanel/><ServiceAnalysis/><section className="panel tag-evidence-panel"><SectionTitle title="Ownership & tag evidence">Understand what is available before making an allocation decision</SectionTitle>{tagged.length ? <div className="observed-tags-grid">{[...new Set(tagged.flatMap(f=>Object.keys(observedTags(f))))].slice(0,12).map(key=><div key={key}><Tags size={16}/><strong>{key}</strong><span>{tagged.filter(f=>key in observedTags(f)).length} observations</span></div>)}</div> : <div className="evidence-unavailable"><Tags size={24}/><div><h3>No tag fields in these observations</h3><p>This is an evidence gap, not a policy-compliance score. Tags and allocation rules have not been configured through this console.</p></div></div>}</section>
  </>;
}

export function Automation() {
  const {token,scan,canAdmin,workspace,entitlements} = useWorkspace();
  const [tab,setTab] = useState('reviews');
  const terraform = entitlements?.can_export_terraform ?? !!workspace?.can_export_terraform;
  return <><div className="page-tabs" role="tablist" aria-label="Automation workflows"><button role="tab" aria-selected={tab==='reviews'} aria-controls="automation-reviews" id="automation-reviews-tab" onClick={()=>setTab('reviews')}><GitPullRequest size={16}/>Review packages</button><button role="tab" aria-selected={tab==='policies'} aria-controls="automation-policies" id="automation-policies-tab" onClick={()=>setTab('policies')}><ShieldCheck size={16}/>Plan guardrails</button></div><div role="tabpanel" id={`automation-${tab}`} aria-labelledby={`automation-${tab}-tab`}>{tab==='reviews'?<GitOpsPanel key={scan?.scan_id||'no-scan'} token={token} scan={scan} canPublish={canAdmin&&terraform} included={terraform}/>:<PlanPolicyPanel token={token}/>}</div><div className="automation-principles"><div><ShieldCheck size={21}/><h3>Evidence first</h3><p>Every review starts from an owned resource snapshot.</p></div><div><FileCode2 size={21}/><h3>Inspect the exact code</h3><p>Preview import artifacts before downloading or publishing.</p></div><div><GitBranch size={21}/><h3>Keep your review process</h3><p>Draft PRs stay within operator-approved repositories.</p></div></div></>;
}

function ScanHistory() {
  const {scans,scan,selectScan,refresh,busy} = useWorkspace();
  const router = useRouter();
  return <section className="panel"><SectionTitle title="Scan history" action={<button className="button secondary" disabled={!!busy} onClick={refresh}>Refresh history</button>}>Saved observations for this workspace</SectionTitle>{scans.length ? <div className="scan-history-list">{scans.map(item=><button key={item.scan_id} className={item.scan_id===scan?.scan_id?'selected':''} onClick={()=>{selectScan(item.scan_id);router.push('/findings');}}><span className="history-icon"><History size={19}/></span><span className="history-main"><strong>{dateTime(item.timestamp)}</strong><small><code>{item.scan_id.slice(0,8)}</code><span>·</span>{item.total_items_found.toLocaleString()} findings{item.data_origin==='legacy_synthetic'&&<span className="mini-badge amber">Historical synthetic</span>}</small></span><span className="history-providers">{(item.cloud_providers||['azure']).map(p=><ProviderBadge provider={p} key={p}/>)}</span><span className="state-badge">{item.status || 'Saved'}</span><ChevronRight size={17}/></button>)}</div> : <EmptyState icon={History} title="No saved scans yet">Your completed scans will appear here with their original observations.</EmptyState>}</section>;
}

export function ActivityView() {
  const {token,canAdmin} = useWorkspace();
  const [tab,setTab] = useState('deliveries');
  return <><div className="page-tabs" role="tablist" aria-label="Activity views"><button role="tab" aria-selected={tab==='deliveries'} id="activity-deliveries-tab" aria-controls="activity-deliveries" onClick={()=>setTab('deliveries')}><Activity size={16}/>Delivery & audit</button><button role="tab" aria-selected={tab==='scans'} id="activity-scans-tab" aria-controls="activity-scans" onClick={()=>setTab('scans')}><History size={16}/>Scan history</button><button role="tab" aria-selected={tab==='ai'} id="activity-ai-tab" aria-controls="activity-ai" onClick={()=>setTab('ai')}><BrainCircuit size={16}/>AI assessments</button></div><div role="tabpanel" id={`activity-${tab}`} aria-labelledby={`activity-${tab}-tab`}>{tab==='deliveries'?<ReliabilityPanel token={token} canAdmin={canAdmin}/>:tab==='ai'?<AIAssessmentHistory/>:<ScanHistory/>}</div></>;
}

function CloudAccounts() {
  const {workspace,scan,setOverlay,canAdmin,planProviders} = useWorkspace();
  const providers = workspace?.providers || ['azure'];
  const descriptions:Record<string,string>={azure:'Azure Resource Graph inventory',aws:'Account-verified AWS resource inventory',gcp:'Google Cloud resource observations',kubernetes:'Prometheus workload request review'};
  return <><section className="panel"><SectionTitle title="Cloud accounts">Providers with at least one authorized scope</SectionTitle><div className="cloud-account-grid">{planProviders(['azure','aws','gcp','kubernetes']).map(provider=><article key={provider} className={`cloud-account ${providers.includes(provider)?'configured':''}`}><div><ProviderBadge provider={provider}/><span className={`connection-state ${providers.includes(provider)?'configured':''}`}><i/>{providers.includes(provider)?'Available':'Not configured'}</span></div><h3>{providerNames[provider]}</h3><p>{descriptions[provider]}</p>{providers.includes(provider)?<Link className="text-link" href={`/findings?provider=${provider}`}>View findings<ArrowRight size={15}/></Link>:<span className="inline-help">Add a scope below to connect</span>}</article>)}</div><div className="settings-notice"><LockKeyhole size={17}/><p>CloudSaver uses keyless, read-only access. This console never asks for client secrets or access keys.</p></div></section><IdentityOnboardingPanel/><CloudScopesEditor/><section className="panel"><SectionTitle title="Workspace scope">Configured limits and authorized cloud scopes</SectionTitle><dl className="settings-key-values"><div><dt>Configured cloud scopes</dt><dd>{workspace?.configured_scope_count ?? workspace?.subscription_ids.length}</dd></div><div><dt>Scopes allowed per scan</dt><dd>{workspace?.max_scopes_per_scan || 'Plan-limited'}</dd></div><div><dt>Latest completed snapshot</dt><dd>{scan ? dateTime(scan.timestamp) : 'No scan yet'}</dd></div></dl>{!!workspace?.subscription_ids.length&&<div className="subscription-list">{workspace.subscription_ids.map(id=><div key={id}><ProviderBadge provider="azure"/><code>{id}</code></div>)}</div>}{canAdmin&&<div className="panel-bottom-action"><button className="button secondary" onClick={()=>setOverlay('scan')}><Plus size={15}/>Scan available sources</button></div>}</section></>;
}

function Integrations() {
  const {token} = useWorkspace();
  const [delivery,setDelivery] = useState<Reliability|null>(null), [git,setGit] = useState<{publishing_enabled:boolean;targets:{repository:string}[]}|null>(null),[error,setError]=useState('');
  useEffect(()=>{const controller=new AbortController();Promise.all([api<Reliability>('/operations/reliability',token,{signal:controller.signal}),api<{publishing_enabled:boolean;targets:{repository:string}[]}>('/gitops/targets',token,{signal:controller.signal})]).then(([d,g])=>{setDelivery(d);setGit(g);}).catch(()=>{if(!controller.signal.aborted)setError('Integration configuration could not be loaded.');});return()=>controller.abort();},[token]);
  return <><section className="panel"><SectionTitle title="Connected workflows">Approved destinations and publishing configuration</SectionTitle>{error&&<Notice tone="error">{error}</Notice>}<div className="integration-grid"><article><span className="integration-logo github-logo"><GitPullRequest size={23}/></span><span className={`state-badge ${git?.targets.length?'configured':''}`}>{git?git.targets.length?'Configured':'No repositories':'Loading…'}</span><h3>GitHub</h3><p>Draft PRs with isolated Terraform import reviews.</p><small>{git ? `${git.targets.length} approved repositories · publishing ${git.publishing_enabled?'enabled':'disabled'}`:'Checking workspace configuration'}</small><Link href="/automation" className="text-link">Open review packages<ArrowRight size={14}/></Link></article>{(['slack','teams'] as const).map(channel=><article key={channel}><span className={`integration-logo ${channel}-logo`}>{channel==='slack'?<span aria-hidden="true">#</span>:<span aria-hidden="true">T</span>}</span><span className="state-badge">{delivery?delivery.targets.some(t=>t.channel===channel)?'Target configured':'No target':'Loading…'}</span><h3>{channel==='slack'?'Slack':'Microsoft Teams'}</h3><p>Aggregate notifications through durable workspace-scoped delivery.</p><small>{delivery?.targets.filter(t=>t.channel===channel).map(t=>t.target_id).join(', ') || 'Configure an approved target with your administrator'}</small><Link href="/activity" className="text-link">Inspect delivery history<ArrowRight size={14}/></Link></article>)}</div></section><section className="panel integration-boundary"><div className="integration-logo"><ClipboardIcon/></div><div><h3>Issue tracking</h3><p>Jira and ServiceNow assignment are not implemented in this release. No issue will be created from a resource review.</p></div><span className="state-badge">Not connected</span></section><Notice>Operator configuration enables outbound publishing and delivery. A configured target does not establish live provider acceptance.</Notice></>;
}

function ClipboardIcon() {return <Layers3 size={22}/>;}

function Plan() {
  const {workspace, entitlements: plan, canBill, planName, token, reloadProfile, notify} = useWorkspace();
  const [options, setOptions] = useState<PlanOption[]>([]);
  const [selected, setSelected] = useState('');
  const [pending, setPending] = useState<{requested_plan_code: string; status: string} | null>(null);
  const [loadError, setLoadError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!canBill || !token) return;
    const controller = new AbortController();
    api<{items: PlanOption[]; current_tier: string; pending_request?: {requested_plan_code: string; status: string}}>(
      '/billing/plans', token, {signal: controller.signal})
      .then(result => {
        setOptions(result.items);
        setSelected(result.current_tier);
        setPending(result.pending_request?.status ? result.pending_request : null);
        setLoadError('');
      })
      .catch(() => { if (!controller.signal.aborted) setLoadError('Plans could not be loaded. Try again.'); });
    return () => controller.abort();
  }, [canBill, token, plan?.tier]);
  if (!plan) return <Loading label="Loading your plan…"/>;
  const quota = Math.min(100, plan.current_subscriptions / Math.max(1, plan.max_subscriptions) * 100);
  const period = planDate(plan.current_period_end);
  const billingUrl = canBill ? manageBillingUrl(plan.manage_billing_url) : null;
  const frequencies = plan.allowed_scan_frequencies || [];
  const features: [string, boolean][] = [['Daily scheduled scans', frequencies.includes('daily')], ['Hourly scheduled scans', frequencies.includes('hourly')], ['Terraform review', plan.can_export_terraform], ['Key Vault', plan.can_use_keyvault], ['Automatic alerts', plan.can_dispatch_automated_alerts]];
  async function savePlan() {
    if (!plan || selected === plan.tier || saving || pending) return;
    setSaving(true);
    try {
      const request = await api<{requested_plan_code: string; status: string}>('/billing/plan-requests', token,
        {method: 'POST', body: {plan_tier: selected, version: plan.settings_version}});
      setPending(request);
      notify(`Your request to move to ${options.find(item => item.code === selected)?.name || selected} was sent for approval.`);
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : 'Plan request could not be sent.', 'error');
    } finally {
      setSaving(false);
    }
  }
  return <><section className="panel billing-panel"><div className="billing-plan"><span className="eyebrow">Your current plan</span><h2>{planName}</h2><p>{period ? `${plan.billing_state === 'active' ? 'Renews on' : 'Ended on'} ${period}` : 'Your workspace limits and included features.'}</p><span className="plan-badge">{billingStateLabels[plan.billing_state] || plan.billing_state}</span></div><div className="billing-details"><h3>Cloud scopes</h3><div className="quota-value"><strong>{plan.current_subscriptions.toLocaleString('en-US')}<span> / {plan.max_subscriptions.toLocaleString('en-US')}</span></strong><span>{Math.round(quota)}% used</span></div><div className="quota-meter" role="meter" aria-label="Cloud scopes used" aria-valuemin={0} aria-valuemax={plan.max_subscriptions} aria-valuenow={plan.current_subscriptions}><i style={{width: `${quota}%`}}/></div><p>{plan.current_subscriptions.toLocaleString('en-US')} of {plan.max_subscriptions.toLocaleString('en-US')} cloud scopes used.</p><div className="plan-features">{features.map(([name, included]) => <div key={name}>{included ? <CheckCircle2 size={16}/> : <MinusCircle size={16}/>}<span>{name}</span><strong>{included ? 'Included' : 'Not included'}</strong></div>)}</div></div></section><section className="panel"><SectionTitle title="Plan limits">Allowances for this workspace and current runtime settings</SectionTitle><dl className="settings-key-values"><div><dt>Resources per scan</dt><dd>{plan.max_resources_per_scan.toLocaleString('en-US')}</dd></div><div><dt>Scan frequencies</dt><dd>{frequencies.map(f => frequencyNames[f] || f).join(', ') || 'Manual'}</dd></div><div><dt>Cloud providers</dt><dd>{(plan.allowed_providers || []).map(p => providerNames[p] || p).join(', ') || 'None'}</dd></div><div><dt>Retention</dt><dd>{plan.retention_days.toLocaleString('en-US')} days</dd></div><div><dt>Scheduled scans</dt><dd>{workspace?.scheduled_scans_enabled ? `On · ${workspace.scan_frequency === 'hourly' ? 'hourly' : 'daily'}` : workspace?.platform_scheduled_scans_enabled === false ? 'Paused by your platform operator' : 'Off'}</dd></div><div><dt>Automatic alerts</dt><dd>{workspace?.automated_alerts_enabled ? 'On' : workspace?.platform_automated_alerts_enabled === false ? 'Paused by your platform operator' : 'Off'}</dd></div></dl>{canBill && plan.plan_change_allowed ? <div className="settings-notice"><CreditCard size={17}/><div><p>Submit a plan change for platform approval. When Stripe billing is enabled, payment will be collected after approval.</p>{loadError && <Notice tone="error">{loadError}</Notice>}{pending ? <p><strong>Pending:</strong> {options.find(item => item.code === pending.requested_plan_code)?.name || pending.requested_plan_code} ({pending.status === 'pending_payment' ? 'awaiting payment' : 'awaiting approval'})</p> : options.length ? <div className="plan-change-row"><label className="field"><span>Plan</span><select value={selected} onChange={event => setSelected(event.target.value)} disabled={!!pending}>{options.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label><button className="button" disabled={saving || !!pending || selected === plan.tier} onClick={savePlan}>{saving ? 'Sending…' : 'Request plan change'}</button></div> : loadError ? null : <Loading label="Loading plans…"/>}{billingUrl ? <a className="text-link" href={billingUrl} target="_blank" rel="noopener noreferrer">Manage billing<ExternalLink size={14}/></a> : null}</div></div> : billingUrl ? <div className="settings-notice"><CreditCard size={17}/><p>Update payment details and view invoices with your billing provider.</p><a className="button secondary" href={billingUrl} target="_blank" rel="noopener noreferrer">Manage billing<ExternalLink size={15}/></a></div> : <div className="settings-notice"><CreditCard size={17}/><p>{CONTACT_ACCOUNT_MANAGER}</p></div>}</section></>;
}

function Preferences() {
  const {workspace,density,setDensity} = useWorkspace();
  return <><section className="panel"><SectionTitle title="Display preferences">Saved locally in this browser; no resource or credential data is stored</SectionTitle><div className="preference-row"><div><h3>Table density</h3><p>Choose the spacing that works best for your inventory reviews.</p></div><div className="segmented-control">{(['compact','medium','relaxed'] as const).map(value=><button key={value} aria-pressed={density===value} onClick={()=>setDensity(value)}>{value.charAt(0)+value.slice(1)}</button>)}</div></div></section><section className="panel"><SectionTitle title="Session & access">Your current workspace identity</SectionTitle><dl className="settings-key-values"><div><dt>Workspace</dt><dd>{workspace?.name}</dd></div><div><dt>Workspace ID</dt><dd><code>{workspace?.tenant_id}</code></dd></div><div><dt>Roles</dt><dd>{workspace?.roles.join(', ')}</dd></div><div><dt>Credential storage</dt><dd>Browser memory only</dd></div></dl></section><section className="panel"><SectionTitle title="Keyboard shortcuts">Move through your reviews without leaving the keyboard</SectionTitle><div className="shortcut-list">{[['⌘ / Ctrl + K','Search pages, actions, and resources'],['G then D','Open overview'],['G then F','Open findings'],['/','Focus inventory search'],['⌘ / Ctrl + A','Select the current findings page'],['Shift + R','Review selected findings'],['Esc','Close the active drawer or dialog']].map(([keys,action])=><div key={keys}><span>{action}</span><kbd>{keys}</kbd></div>)}</div></section></>;
}

export function SettingsView() {
  const [tab,setTab] = useState('accounts');
  const tabs = [{id:'accounts',label:'Cloud accounts',icon:Cloud},{id:'schedule',label:'Schedule & alerts',icon:Bell},{id:'integrations',label:'Integrations',icon:GitBranch},{id:'plan',label:'Plan',icon:CreditCard},{id:'preferences',label:'Preferences & access',icon:Settings2}];
  return <><div className="page-tabs" role="tablist" aria-label="Workspace settings">{tabs.map(item=><button role="tab" key={item.id} id={`settings-${item.id}-tab`} aria-controls={`settings-${item.id}`} aria-selected={tab===item.id} onClick={()=>setTab(item.id)}><item.icon size={16}/>{item.label}</button>)}</div><div role="tabpanel" id={`settings-${tab}`} aria-labelledby={`settings-${tab}-tab`}>{tab==='accounts'?<CloudAccounts/>:tab==='schedule'?<ScheduleAlertsEditor/>:tab==='integrations'?<Integrations/>:tab==='plan'?<Plan/>:<Preferences/>}</div></>;
}
