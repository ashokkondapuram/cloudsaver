'use client';

import {createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {api, watchUnauthorized, ApiError} from '../lib/api';
import {validateProfile,validateScan,validateWorkspaceEvidence} from '../lib/session-contract';
import {findingKey} from '../lib/finops';
import type {Density, Entitlements, Finding, Scan, Workspace} from '../lib/types';
import {UiThemeApplier} from './UiThemeApplier';
import {AutoScanOrchestrator} from './AutoScanOrchestrator';

type Overlay = 'command' | 'workspace' | 'notifications' | 'finding' | 'review' | null;
type WorkspaceState = {
  token: string; workspace: Workspace | null; entitlements: Entitlements | null;
  scans: Scan[]; scan: Scan | undefined; busy: string; scanActivity: string; error: string;
  canAdmin: boolean; canBill: boolean; scope: string[]; setScope: (value: string[]) => void;
  overlay: Overlay; setOverlay: (value: Overlay) => void;
  finding: Finding | null; findingFocusKey:string|null; findingContext: Finding[]; openFinding: (finding: Finding, context?: Finding[]) => void;
  review: Finding[]; openReview: (findings: Finding[]) => void;
  selection: Finding[]; setSelection: (findings: Finding[]) => void;
  density: Density; setDensity: (value: Density) => void;
  notice: {text: string; tone: 'success' | 'error' | 'info' | 'warning'} | null;
  notify: (text: string, tone?: 'success' | 'error' | 'info' | 'warning') => void; clearNotice: () => void;
  connect: (token: string) => Promise<void>; disconnect: () => void;
  selectScan: (id: string) => void;
  runScan: (providers: string[], options?: {automatic?: boolean}) => void;
  refresh: () => Promise<void>; reloadProfile: () => Promise<void>;
  liveScanEpoch: number;
  planName: string; planProviders: (providers: string[]) => string[];
};

const Context = createContext<WorkspaceState | null>(null);
export function useWorkspace() {const value = useContext(Context); if (!value) throw new Error('Workspace provider is required'); return value;}

const IDLE_TIMEOUT_MS = 30 * 60 * 1000;
const TOKEN_KEY = 'cloudsaver:session:token';
const ACTIVITY_KEY = 'cloudsaver:session:activity';

function readSavedToken() {
  try {
    const savedToken = sessionStorage.getItem(TOKEN_KEY);
    const lastActive = Number(sessionStorage.getItem(ACTIVITY_KEY) || 0);
    if (!savedToken || !lastActive || Date.now() - lastActive > IDLE_TIMEOUT_MS) {
      sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(ACTIVITY_KEY);
      return '';
    }
    return savedToken;
  } catch {
    return '';
  }
}

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
  const [liveScanEpoch, setLiveScanEpoch] = useState(0);
  const [scanActivity, setScanActivity] = useState('');
  const findingFocusKey=useRef<string|null>(null);
  const session = useRef(0);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const activeCredential=useRef('');
  const connecting = useRef<AbortController | null>(null);

  useEffect(() => {try {const saved = localStorage.getItem('cloudsaver:ui:density'); if (saved === 'compact' || saved === 'medium' || saved === 'relaxed') updateDensity(saved);} catch {}}, []);
  useEffect(() => {if (!notice) return; const timer = setTimeout(() => setNotice(null), 6500); return () => clearTimeout(timer);}, [notice]);

  // Restores a reloaded tab's session if it hasn't been idle past the timeout.
  useEffect(() => {
    const saved = readSavedToken();
    if (saved) connect(saved, {persist: false}).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tracks activity while connected; signs out automatically after IDLE_TIMEOUT_MS of inactivity.
  useEffect(() => {
    if (!token) return;
    const markActive = () => {try {sessionStorage.setItem(ACTIVITY_KEY, String(Date.now()));} catch {}};
    markActive();
    const events = ['mousedown', 'keydown', 'scroll', 'touchstart'] as const;
    events.forEach(name => window.addEventListener(name, markActive, {passive: true}));
    const interval = setInterval(() => {
      let lastActive = 0;
      try {lastActive = Number(sessionStorage.getItem(ACTIVITY_KEY) || 0);} catch {}
      if (lastActive && Date.now() - lastActive > IDLE_TIMEOUT_MS) disconnect();
    }, 30000);
    return () => {events.forEach(name => window.removeEventListener(name, markActive)); clearInterval(interval);};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  const notify = useCallback((text: string, tone: 'success' | 'error' | 'info' | 'warning' = 'success') => setNotice({text, tone}), []);
  const setDensity = (value: Density) => {updateDensity(value); try {localStorage.setItem('cloudsaver:ui:density', value);} catch {}};

  function clearContext() {findingFocusKey.current=null;setFinding(null);setFindingContext([]); setReview([]); setSelection([]); setScope([]);}
  function selectScan(id: string) {setSelected(id); clearContext(); setOverlay(null);}

  async function connect(credential: string, options: {persist?: boolean} = {}) {
    const persist = options.persist !== false;
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
      validateWorkspaceEvidence(me,history,plan);
      activeCredential.current=nextToken;
      setToken(nextToken); setWorkspace(me); setEntitlements(plan);
      setScans(history); setSelected(history[0]?.scan_id || '');
      clearContext(); setOverlay(null);
      if (persist) {try {sessionStorage.setItem(TOKEN_KEY, nextToken); sessionStorage.setItem(ACTIVITY_KEY, String(Date.now()));} catch {}}
    } catch (cause) {
      if (session.current === version && !controller.signal.aborted) {
        try {sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(ACTIVITY_KEY);} catch {}
        const message = cause instanceof Error ? cause.message : 'Workspace could not be connected.';
        setError(message); throw new Error(message);
      }
    } finally {if (session.current === version) setBusy('');}
  }

  useEffect(()=>{
    if(!token)return;
    return watchUnauthorized(token,()=>{if(activeCredential.current!==token)return;disconnect();setError('Your session ended. Connect again to continue.');});
  },[token]);

  function disconnect() {
    activeCredential.current='';
    session.current++; connecting.current?.abort();
    try {sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(ACTIVITY_KEY);} catch {}
    setToken(''); setWorkspace(null); setEntitlements(null); setScans([]); setSelected('');
    setBusy(''); setScanActivity(''); setError(''); setOverlay(null); setNotice(null); clearContext();
  }

  async function syncRunningScan(version: number) {
    if (version !== session.current) return false;
    try {
      const history = await api<Scan[]>('/scans', token);
      if (version !== session.current) return false;
      const running = history.find(entry => entry.status === 'running');
      setScans(history);
      if (running) {
        const current = selectedRef.current;
        const next = !current || !history.some(s => s.scan_id === current) ? running.scan_id : current;
        if (next !== current) setSelected(next);
        if (next === running.scan_id) setLiveScanEpoch(epoch => epoch + 1);
        return true;
      }
      const latest = history[0];
      if (latest?.status === 'completed' && scanActivity) {
        setSelected(current => (current && history.some(s => s.scan_id === current) ? current : latest.scan_id));
        clearContext();
        notify(`Scan completed. ${latest.total_items_found.toLocaleString()} findings ready to review.`);
      }
      return false;
    } catch {
      return true;
    }
  }

  function runScan(providers: string[], options?: {automatic?: boolean}) {
    const version = session.current;
    setScanActivity('Scan in progress');
    setError('');
    setOverlay(null);
    if (!options?.automatic) notify('Scan started. You can keep working while inventory loads.', 'info');
    let poll: number | undefined;
    const stop = () => {
      if (poll) window.clearInterval(poll);
      poll = undefined;
      if (version === session.current) setScanActivity('');
    };
    const tick = async () => {
      const stillRunning = await syncRunningScan(version);
      if (!stillRunning) stop();
    };
    poll = window.setInterval(() => { void tick(); }, 8000);
    void tick();
    void api<Scan>('/scans/multi-cloud', token, {body: {providers}, timeoutMs: 120_000}).then(result => {
      if (version !== session.current) return;
      validateScan(result);
      setScans(previous => [result, ...previous.filter(s => s.scan_id !== result.scan_id)]);
      setSelected(result.scan_id);
      if (result.status === 'completed') {
        clearContext();
        notify(`Scan completed. ${result.total_items_found.toLocaleString()} findings ready to review.`);
        stop();
      }
    }).catch(cause => {
      if (version !== session.current) return;
      if (cause instanceof ApiError && cause.uncertain) {
        notify('Scan may still be running. Check scan history before you start another.', 'info');
        return;
      }
      const message = cause instanceof Error ? cause.message : 'Scan could not be completed.';
      setError(message);
      notify(message, 'error');
      stop();
    });
  }

  useEffect(() => {
    if (!token || scanActivity || !scans.some(entry => entry.status === 'running')) return;
    setScanActivity('Scan in progress');
    const version = session.current;
    const poll = window.setInterval(() => {
      void syncRunningScan(version).then(stillRunning => {
        if (!stillRunning && version === session.current) setScanActivity('');
      });
    }, 8000);
    return () => window.clearInterval(poll);
  }, [token, scans, scanActivity]);

  async function refresh() {
    const version = session.current;
    setBusy('Refreshing workspace'); setError('');
    try {
      const [history, me, plan] = await Promise.all([api<Scan[]>('/scans', token), api<Workspace>('/me', token), api<Entitlements>('/billing/entitlements', token)]);
      if (version !== session.current) return;
      validateWorkspaceEvidence(me,history,plan);
      setScans(history); setWorkspace(me); setEntitlements(plan);
      setSelected(previous => history.some(s => s.scan_id === previous) ? previous : history[0]?.scan_id || '');
      clearContext(); notify('Workspace is up to date.');
    } catch (cause) {if (version === session.current) notify(cause instanceof Error ? cause.message : 'Refresh failed.', 'error');}
    finally {if (version === session.current) setBusy('');}
  }

  async function reloadProfile() {
    const version = session.current;
    const [me, plan] = await Promise.all([api<Workspace>('/me', token), api<Entitlements>('/billing/entitlements', token)]);
    if (version === session.current) {validateProfile(me,plan);setWorkspace(me); setEntitlements(plan);}
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
  return <Context.Provider value={{token, workspace, entitlements, scans, scan, busy, scanActivity, error, canAdmin, canBill: canAdmin || !!workspace?.roles.includes('BillingAdmin'), planName, planProviders,
    scope, setScope: value => {setScope(value); setSelection([]);}, overlay, setOverlay, finding, findingContext, findingFocusKey:findingFocusKey.current, openFinding,
    review, openReview, selection, setSelection,
    density, setDensity, notice, notify, clearNotice: () => setNotice(null), connect, disconnect, selectScan, runScan, refresh, reloadProfile, liveScanEpoch}}><UiThemeApplier/><AutoScanOrchestrator/>{children}</Context.Provider>;
}
