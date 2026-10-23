'use client';

import {createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {api} from '../lib/api';
import {findingKey} from '../lib/finops';
import type {Density, Entitlements, Finding, Scan, Workspace} from '../lib/types';

type Overlay = 'command' | 'scan' | 'workspace' | 'notifications' | 'finding' | 'review' | null;
type WorkspaceState = {
  token: string; workspace: Workspace | null; entitlements: Entitlements | null;
  scans: Scan[]; scan: Scan | undefined; busy: string; error: string;
  canAdmin: boolean; canBill: boolean; scope: string[]; setScope: (value: string[]) => void;
  overlay: Overlay; setOverlay: (value: Overlay) => void;
  finding: Finding | null; findingFocusKey:string|null; findingContext: Finding[]; openFinding: (finding: Finding, context?: Finding[]) => void;
  review: Finding[]; openReview: (findings: Finding[]) => void;
  selection: Finding[]; setSelection: (findings: Finding[]) => void;
  density: Density; setDensity: (value: Density) => void;
  notice: {text: string; tone: 'success' | 'error' | 'info'} | null;
  notify: (text: string, tone?: 'success' | 'error' | 'info') => void; clearNotice: () => void;
  connect: (token: string) => Promise<void>; disconnect: () => void;
  selectScan: (id: string) => void; runScan: (providers: string[]) => Promise<void>;
  refresh: () => Promise<void>; reloadProfile: () => Promise<void>;
  planName: string; planProviders: (providers: string[]) => string[];
};

const Context = createContext<WorkspaceState | null>(null);
export function useWorkspace() {const value = useContext(Context); if (!value) throw new Error('Workspace provider is required'); return value;}

export function WorkspaceProvider({children}: {children: ReactNode}) {
  const [token, setToken] = useState('');
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [scans, setScans] = useState<Scan[]>([]);
  const [selected, setSelected] = useState('');
  const [scope, setScope] = useState<string[]>([]);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [finding, setFinding] = useState<Finding | null>(null);
  const [findingContext,setFindingContext] = useState<Finding[]>([]);
  const [review, setReview] = useState<Finding[]>([]);
  const [selection, setSelection] = useState<Finding[]>([]);
  const [density, updateDensity] = useState<Density>('medium');
  const [notice, setNotice] = useState<WorkspaceState['notice']>(null);
  const findingFocusKey=useRef<string|null>(null);
  const session = useRef(0);
  const connecting = useRef<AbortController | null>(null);

  useEffect(() => {try {const saved = localStorage.getItem('cloudsaver:ui:density'); if (saved === 'compact' || saved === 'medium' || saved === 'relaxed') updateDensity(saved);} catch {}}, []);
  useEffect(() => {if (!notice) return; const timer = setTimeout(() => setNotice(null), 6500); return () => clearTimeout(timer);}, [notice]);
  const notify = useCallback((text: string, tone: 'success' | 'error' | 'info' = 'success') => setNotice({text, tone}), []);
  const setDensity = (value: Density) => {updateDensity(value); try {localStorage.setItem('cloudsaver:ui:density', value);} catch {}};

  function clearContext() {findingFocusKey.current=null;setFinding(null);setFindingContext([]); setReview([]); setSelection([]); setScope([]);}
  function selectScan(id: string) {setSelected(id); clearContext(); setOverlay(null);}

  async function connect(credential: string) {
    connecting.current?.abort();
    const controller = new AbortController(); connecting.current = controller;
    const version = ++session.current;
    setBusy('Connecting workspace'); setError('');
    try {
      const nextToken = credential.trim();
      const [me, history, plan] = await Promise.all([
        api<Workspace>('/me', nextToken, {signal: controller.signal}),
        api<Scan[]>('/scans', nextToken, {signal: controller.signal}),
        api<Entitlements>('/billing/entitlements', nextToken, {signal: controller.signal}),
      ]);
      if (session.current !== version) return;
      setToken(nextToken); setWorkspace(me); setEntitlements(plan);
      setScans(history); setSelected(history[0]?.scan_id || '');
      clearContext(); setOverlay(null);
    } catch (cause) {
      if (session.current === version && !controller.signal.aborted) {
        const message = cause instanceof Error ? cause.message : 'Workspace could not be connected.';
        setError(message); throw new Error(message);
      }
    } finally {if (session.current === version) setBusy('');}
  }

  function disconnect() {
    session.current++; connecting.current?.abort();
    setToken(''); setWorkspace(null); setEntitlements(null); setScans([]); setSelected('');
    setBusy(''); setError(''); setOverlay(null); setNotice(null); clearContext();
  }

  async function runScan(providers: string[]) {
    const version = session.current;
    setBusy('Scanning cloud resources'); setError(''); setOverlay(null);
    try {
      const result = await api<Scan>('/scans/multi-cloud', token, {body: {providers}});
      if (version !== session.current) return;
      setScans(previous => [result, ...previous.filter(s => s.scan_id !== result.scan_id)]);
      setSelected(result.scan_id); clearContext(); notify(`Scan completed. ${result.total_items_found.toLocaleString()} findings ready to review.`);
    } catch (cause) {if (version === session.current) {const message = cause instanceof Error ? cause.message : 'Scan could not be completed.'; setError(message); notify(message, 'error');}}
    finally {if (version === session.current) setBusy('');}
  }

  async function refresh() {
    const version = session.current;
    setBusy('Refreshing workspace'); setError('');
    try {
      const [history, me, plan] = await Promise.all([api<Scan[]>('/scans', token), api<Workspace>('/me', token), api<Entitlements>('/billing/entitlements', token)]);
      if (version !== session.current) return;
      setScans(history); setWorkspace(me); setEntitlements(plan);
      setSelected(previous => history.some(s => s.scan_id === previous) ? previous : history[0]?.scan_id || '');
      clearContext(); notify('Workspace is up to date.');
    } catch (cause) {if (version === session.current) notify(cause instanceof Error ? cause.message : 'Refresh failed.', 'error');}
    finally {if (version === session.current) setBusy('');}
  }

  async function reloadProfile() {
    const version = session.current;
    const [me, plan] = await Promise.all([api<Workspace>('/me', token), api<Entitlements>('/billing/entitlements', token)]);
    if (version === session.current) {setWorkspace(me); setEntitlements(plan);}
  }

  const openFinding = useCallback((value: Finding, context: Finding[] = []) => {
    const active=document.activeElement as HTMLElement|null;
    // Capture before virtual rows can rerender; comparison buttons keep the original opener.
    if(active?.closest('dialog')?.getAttribute('aria-label')!=='Finding details')
      findingFocusKey.current=active?.getAttribute('data-focus-return')||findingKey(value);
    setFinding(value);setFindingContext(context.length?context:[value]);setOverlay('finding');
  }, []);
  const openReview = useCallback((values: Finding[]) => {setReview(values); setOverlay('review');}, []);
  const scan = scans.find(s => s.scan_id === selected) || scans[0];
  const canAdmin = !!workspace?.roles.includes('TenantAdmin');
  const planName = entitlements?.plan_name || workspace?.plan_name || workspace?.plan_tier || '';
  const planProviders = (providers: string[]) => entitlements?.allowed_providers ? providers.filter(p => entitlements.allowed_providers.includes(p)) : providers;
  return <Context.Provider value={{token, workspace, entitlements, scans, scan, busy, error, canAdmin, canBill: canAdmin || !!workspace?.roles.includes('BillingAdmin'), planName, planProviders,
    scope, setScope: value => {setScope(value); setSelection([]);}, overlay, setOverlay, finding, findingContext, findingFocusKey:findingFocusKey.current, openFinding,
    review, openReview, selection, setSelection,
    density, setDensity, notice, notify, clearNotice: () => setNotice(null), connect, disconnect, selectScan, runScan, refresh, reloadProfile}}>{children}</Context.Provider>;
}
