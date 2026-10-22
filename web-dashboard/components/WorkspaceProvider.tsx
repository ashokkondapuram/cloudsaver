'use client';

import {createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {api} from '../lib/api';
import type {Density, Entitlements, Finding, Scan, Workspace} from '../lib/types';

type Overlay = 'command' | 'scan' | 'workspace' | 'notifications' | 'finding' | 'review' | null;
type WorkspaceState = {
  token: string; workspace: Workspace | null; entitlements: Entitlements | null;
  scans: Scan[]; scan: Scan | undefined; busy: string; error: string;
  canAdmin: boolean; canBill: boolean; scope: string[]; setScope: (value: string[]) => void;
  overlay: Overlay; setOverlay: (value: Overlay) => void;
  finding: Finding | null; openFinding: (finding: Finding) => void;
  review: Finding[]; openReview: (findings: Finding[]) => void;
  selection: Finding[]; setSelection: (findings: Finding[]) => void;
  density: Density; setDensity: (value: Density) => void;
  notice: {text: string; tone: 'success' | 'error' | 'info'} | null;
  notify: (text: string, tone?: 'success' | 'error' | 'info') => void; clearNotice: () => void;
  connect: (token: string) => Promise<void>; disconnect: () => void;
  selectScan: (id: string) => void; runScan: (providers: string[]) => Promise<void>;
  refresh: () => Promise<void>; checkout: () => Promise<void>;
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
  const [review, setReview] = useState<Finding[]>([]);
  const [selection, setSelection] = useState<Finding[]>([]);
  const [density, updateDensity] = useState<Density>('medium');
  const [notice, setNotice] = useState<WorkspaceState['notice']>(null);
  const session = useRef(0);
  const connecting = useRef<AbortController | null>(null);
  const checkoutKey = useRef<string | null>(null);

  useEffect(() => {try {const saved = localStorage.getItem('cloudsaver:ui:density'); if (saved === 'compact' || saved === 'medium' || saved === 'relaxed') updateDensity(saved);} catch {}}, []);
  useEffect(() => {if (!notice) return; const timer = setTimeout(() => setNotice(null), 6500); return () => clearTimeout(timer);}, [notice]);
  const notify = useCallback((text: string, tone: 'success' | 'error' | 'info' = 'success') => setNotice({text, tone}), []);
  const setDensity = (value: Density) => {updateDensity(value); try {localStorage.setItem('cloudsaver:ui:density', value);} catch {}};

  function clearContext() {setFinding(null); setReview([]); setSelection([]); setScope([]);}
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
      clearContext(); checkoutKey.current = null; setOverlay(null);
    } catch (cause) {
      if (session.current === version && !controller.signal.aborted) {
        const message = cause instanceof Error ? cause.message : 'Workspace could not be connected.';
        setError(message); throw new Error(message);
      }
    } finally {if (session.current === version) setBusy('');}
  }

  function disconnect() {
    session.current++; connecting.current?.abort(); checkoutKey.current = null;
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

  async function checkout() {
    const version = session.current;
    setBusy('Preparing checkout');
    // Open synchronously so browser popup protection does not lose an async checkout.
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    try {
      const result = await api<{checkout_url: string}>('/billing/checkout', token, {body: {target_tier: 'GROWTH', idempotency_key: (checkoutKey.current ||= crypto.randomUUID())}});
      if (version !== session.current) {tab?.close(); return;}
      const url = new URL(result.checkout_url);
      if (url.protocol !== 'https:' || url.hostname !== 'checkout.stripe.com') throw new Error('Checkout returned an unexpected destination.');
      if (tab) tab.location.href = url.href;
      else notify('Allow popups for this workspace and try checkout again.', 'info');
    } catch (cause) {tab?.close(); if (version === session.current) notify(cause instanceof Error ? cause.message : 'Checkout is unavailable.', 'error');}
    finally {if (version === session.current) setBusy('');}
  }

  const openFinding = useCallback((value: Finding) => {setFinding(value); setOverlay('finding');}, []);
  const openReview = useCallback((values: Finding[]) => {setReview(values); setOverlay('review');}, []);
  const scan = scans.find(s => s.scan_id === selected) || scans[0];
  const canAdmin = !!workspace?.roles.includes('TenantAdmin');
  return <Context.Provider value={{token, workspace, entitlements, scans, scan, busy, error, canAdmin, canBill: canAdmin || !!workspace?.roles.includes('BillingAdmin'),
    scope, setScope: value => {setScope(value); setSelection([]);}, overlay, setOverlay, finding, openFinding,
    review, openReview, selection, setSelection,
    density, setDensity, notice, notify, clearNotice: () => setNotice(null), connect, disconnect, selectScan, runScan, refresh, checkout}}>{children}</Context.Provider>;
}
