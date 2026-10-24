'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect, useMemo, useState} from 'react';
import {Activity, BrainCircuit, ArrowRight, Bell, Blocks, Check, CheckCircle2, ChevronRight, Cloud, CreditCard, Database, ExternalLink, FileCode2, Fingerprint, GitBranch, GitPullRequest, History, KeyRound, Layers3, LockKeyhole, MinusCircle, Plus, Settings2, ShieldCheck, Tags, Target, Wallet} from 'lucide-react';
import {api} from '../lib/api';
import {dateTime, money, opportunityTotals, observedTags, providerNames, providerOf, scopeOf} from '../lib/finops';
import {CONTACT_ACCOUNT_MANAGER, billingStateLabels, frequencyNames, manageBillingUrl, planDate} from '../lib/plan';
import type {Entitlements, Finding, PlanOption, Reliability} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {useScopedFindings} from './Overview';
import {BillingEvidencePanel,AIAssessmentHistory} from './EnterpriseEvidence';
import {EmptyState, Loading, Notice, ProviderBadge, SectionTitle} from './ui/shared';
import {AIFoundryConfigurationEditor} from './settings/AIFoundryConfigurationEditor';
import {CloudScopesEditor, IdentityOnboardingPanel, ResourceAccessIdentityEditor, ScheduleAlertsEditor} from './settings/WorkspaceSettings';
import {AccessSettings} from './settings/AccessSettings';
import {CustomerRuleSettings} from './rules/CustomerRuleSettings';
import {DataGovernanceWorkspace} from './settings/DataGovernanceWorkspace';

function ScanHistory() {
  const {scans,scan,selectScan,refresh,busy} = useWorkspace();
  const router = useRouter();
  return <section className="panel"><SectionTitle title="Scan history" action={<button className="button secondary" disabled={!!busy} onClick={refresh}>Refresh history</button>}>Saved observations for this workspace</SectionTitle>{scans.length ? <div className="scan-history-list">{scans.map(item=><button key={item.scan_id} className={item.scan_id===scan?.scan_id?'selected':''} onClick={()=>{selectScan(item.scan_id);router.push('/resources');}}><span className="history-icon"><History size={19}/></span><span className="history-main"><strong>{dateTime(item.timestamp)}</strong><small><code>{item.scan_id.slice(0,8)}</code><span>·</span>{item.total_items_found.toLocaleString()} findings{item.data_origin==='legacy_synthetic'&&<span className="mini-badge amber">Historical synthetic</span>}</small></span><span className="history-providers">{(item.cloud_providers||['azure']).map(p=><ProviderBadge provider={p} key={p}/>)}</span><span className="state-badge">{item.status || 'Saved'}</span><ChevronRight size={17}/></button>)}</div> : <EmptyState icon={History} title="No saved scans yet">Your completed scans will appear here with their original observations.</EmptyState>}</section>;
}

function ActivityView() {
  const {token}=useWorkspace();const [data,setData]=useState<Reliability|null>(null),[error,setError]=useState('');
  useEffect(()=>{const c=new AbortController();api<Reliability>('/operations/reliability',token,{signal:c.signal}).then(d=>{if(!c.signal.aborted)setData(d);}).catch(e=>{if(!c.signal.aborted)setError((e as Error).message);});return()=>c.abort();},[token]);
  return <details className="panel"><summary>Workspace activity and delivery</summary>{error&&<Notice tone="error">{error}</Notice>}<p>{data?.available?'Durable delivery is configured.':'Durable delivery status is unavailable.'} Delivery retries remain an explicit administrator operation through the audited API.</p><ScanHistory/><AIAssessmentHistory/></details>;
}

function CloudAccounts() {
  const {workspace,scan,setOverlay,canAdmin,planProviders} = useWorkspace();
  const providers = workspace?.providers || ['azure'];
  const descriptions:Record<string,string>={azure:'Azure Resource Graph inventory',aws:'Account-verified AWS resource inventory',gcp:'Google Cloud resource observations',kubernetes:'Prometheus workload request review'};
  return <><section className="panel"><SectionTitle title="Cloud accounts">Providers with at least one authorized scope</SectionTitle><div className="cloud-account-grid">{planProviders(['azure','aws','gcp','kubernetes']).map(provider=><article key={provider} className={`cloud-account ${providers.includes(provider)?'configured':''}`}><div><ProviderBadge provider={provider}/><span className={`connection-state ${providers.includes(provider)?'configured':''}`}><i/>{providers.includes(provider)?'Available':'Not configured'}</span></div><h3>{providerNames[provider]}</h3><p>{descriptions[provider]}</p>{providers.includes(provider)?<Link className="text-link" href={`/resources?provider=${provider}`}>View findings<ArrowRight size={15}/></Link>:<span className="inline-help">Add a scope below to connect</span>}</article>)}</div><div className="settings-notice"><LockKeyhole size={17}/><p>CloudSaver uses keyless, read-only access. This console never asks for client secrets or access keys.</p></div></section><CloudScopesEditor/><section className="panel"><SectionTitle title="Workspace scope">Configured limits and authorized cloud scopes</SectionTitle><dl className="settings-key-values"><div><dt>Configured cloud scopes</dt><dd>{workspace?.configured_scope_count ?? workspace?.subscription_ids.length}</dd></div><div><dt>Scopes allowed per scan</dt><dd>{workspace?.max_scopes_per_scan || 'Plan-limited'}</dd></div><div><dt>Latest completed snapshot</dt><dd>{scan ? dateTime(scan.timestamp) : 'No scan yet'}</dd></div></dl>{!!workspace?.subscription_ids.length&&<div className="subscription-list">{workspace.subscription_ids.map(id=><div key={id}><ProviderBadge provider="azure"/><code>{id}</code></div>)}</div>}{canAdmin&&<div className="panel-bottom-action"><button className="button secondary" onClick={()=>setOverlay('scan')}><Plus size={15}/>Scan available sources</button></div>}</section></>;
}

function ResourceAccessSettings() {
  const {token, canAdmin, notify} = useWorkspace();
  const [testing, setTesting] = useState(false);
  const [results, setResults] = useState<{provider: string; status: string; message: string}[]>([]);
  async function testAccess() {
    if (!canAdmin || testing) return;
    setTesting(true);
    setResults([]);
    try {
      const response = await api<{providers: {provider: string; status: string; message: string}[]}>('/settings/access-test', token, {method: 'POST'});
      setResults(response.providers || []);
      notify('Access test finished.');
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : 'Access test could not run.', 'error');
    } finally {
      setTesting(false);
    }
  }
  return <><IdentityOnboardingPanel/><ResourceAccessIdentityEditor/><section className="panel"><SectionTitle title="Test access" action={canAdmin ? <button type="button" className="button secondary" disabled={testing} onClick={() => void testAccess()}>{testing ? 'Testing…' : 'Test access'}</button> : undefined}>Check read-only access for this workspace before you run a scan</SectionTitle>{!canAdmin && <Notice tone="info">A workspace administrator can run access tests.</Notice>}{results.length ? <dl className="settings-key-values">{results.map(row => <div key={row.provider}><dt>{providerNames[row.provider] || row.provider}</dt><dd>{row.message || row.status}</dd></div>)}</dl> : <p className="inline-help">Runs a short probe per configured cloud provider. No secrets are shown.</p>}</section></>;
}

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
  const features: [string, boolean][] = [['Daily scheduled scans', frequencies.includes('daily')], ['Hourly scheduled scans', frequencies.includes('hourly')], ['Key Vault', plan.can_use_keyvault], ['Automatic alerts', plan.can_dispatch_automated_alerts]];
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
  return <><section className="panel"><SectionTitle title="Display preferences">Saved locally in this browser; no resource or credential data is stored</SectionTitle><div className="preference-row"><div><h3>Table density</h3><p>Choose the spacing that works best for your inventory reviews.</p></div><div className="segmented-control">{(['compact','medium','relaxed'] as const).map(value=><button key={value} aria-pressed={density===value} onClick={()=>setDensity(value)}>{value.charAt(0)+value.slice(1)}</button>)}</div></div></section><section className="panel"><SectionTitle title="Session & access">Your current workspace identity</SectionTitle><dl className="settings-key-values"><div><dt>Workspace</dt><dd>{workspace?.name}</dd></div><div><dt>Workspace ID</dt><dd><code>{workspace?.tenant_id}</code></dd></div><div><dt>Roles</dt><dd>{workspace?.roles.join(', ')}</dd></div><div><dt>Credential storage</dt><dd>Browser memory only</dd></div></dl></section><section className="panel"><SectionTitle title="Keyboard shortcuts">Move through your reviews without leaving the keyboard</SectionTitle><div className="shortcut-list">{[['⌘ / Ctrl + K','Search pages, actions, and resources'],['G then D','Open overview'],['G then R','Open resources'],['/','Focus inventory search'],['Esc','Close the active drawer or dialog']].map(([keys,action])=><div key={keys}><span>{action}</span><kbd>{keys}</kbd></div>)}</div></section></>;
}

export function SettingsView() {
  const [tab,setTab]=useState('cloud');
  useEffect(()=>{const value=new URLSearchParams(window.location.search).get('tab');if(value&&['cloud','rules','ai','access'].includes(value))setTab(value);},[]);
  const tabs=[{id:'cloud',label:'Cloud scopes & billing',icon:Cloud},{id:'rules',label:'Analysis rules',icon:ShieldCheck},{id:'ai',label:'AI & data governance',icon:BrainCircuit},{id:'access',label:'Access & API keys',icon:KeyRound}];
  function choose(value:string){setTab(value);const url=new URL(window.location.href);url.searchParams.set('tab',value);window.history.replaceState(null,'',url);}
  return <><div className="page-tabs" role="tablist" aria-label="Workspace settings" onKeyDown={e=>{if(!['ArrowRight','ArrowLeft','Home','End'].includes(e.key))return;e.preventDefault();const index=tabs.findIndex(t=>t.id===tab);const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length;choose(tabs[next].id);document.getElementById(`settings-${tabs[next].id}-tab`)?.focus();}}>{tabs.map(item=><button role="tab" key={item.id} tabIndex={tab===item.id?0:-1} id={`settings-${item.id}-tab`} aria-controls={`settings-${item.id}`} aria-selected={tab===item.id} onClick={()=>choose(item.id)}><item.icon size={16}/>{item.label}</button>)}</div><div role="tabpanel" tabIndex={0} id={`settings-${tab}`} aria-labelledby={`settings-${tab}-tab`}>{tab==='cloud'?<><CloudAccounts/><ResourceAccessSettings/><ScheduleAlertsEditor/><Plan/><BillingEvidencePanel/><ActivityView/></>:tab==='rules'?<CustomerRuleSettings/>:tab==='ai'?<><AIFoundryConfigurationEditor/><DataGovernanceWorkspace/></>:<><AccessSettings/><Preferences/></>}</div></>;
}
