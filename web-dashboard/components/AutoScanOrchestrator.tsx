'use client';

import {useEffect, useRef} from 'react';
import {
  AUTO_SCAN_CHANNEL,
  cooldownActive,
  postTabAttempt,
  writeCooldown,
  type AutoScanRecord,
} from '../lib/auto-scan-coordination';
import {isLiveSnapshot, useResources} from '../lib/resources';
import {useWorkspace} from './WorkspaceProvider';

/**
 * Starts a multi-cloud inventory scan when there is no snapshot yet, or when
 * the overview resource rows include `analysis_stale` (per-resource staleness).
 * Tenant admins only.
 */
export function AutoScanOrchestrator() {
  const {token, workspace, scans, scan, canAdmin, scanActivity, planProviders, runScan, liveScanEpoch} = useWorkspace();
  const tenantId = workspace?.tenant_id || '';
  const live = isLiveSnapshot(scan);
  const inProgress = scan?.status === 'running';
  const {page, loading: overviewLoading, progress} = useResources(scan?.scan_id, token, live && !!scan?.scan_id, inProgress ? liveScanEpoch : 0, {
    running: inProgress,
    overview: !inProgress,
  });

  const lastTenant = useRef('');

  useEffect(() => {
    if (tenantId && lastTenant.current && tenantId !== lastTenant.current) {
      lastTenant.current = tenantId;
      return;
    }
    lastTenant.current = tenantId;
  }, [tenantId]);

  useEffect(() => {
    if (!tenantId) return;
    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel(AUTO_SCAN_CHANNEL);
      channel.onmessage = (event: MessageEvent<AutoScanRecord>) => {
        if (event.data?.tenantId === tenantId) writeCooldown(event.data);
      };
    } catch {
      channel = null;
    }
    return () => channel?.close();
  }, [tenantId]);

  useEffect(() => {
    if (!token || !workspace || !canAdmin || !tenantId) return;
    if (scanActivity) return;
    if (scans.some(s => s.status === 'running')) return;
    if (cooldownActive(tenantId)) return;

    const providers = planProviders(workspace.allowed_providers ?? workspace.providers ?? ['azure']).filter(Boolean);
    if (!providers.length) return;

    const attempt = (reason: 'bootstrap' | 'stale') => {
      if (cooldownActive(tenantId)) return;
      const attemptedAt = Date.now();
      const record: AutoScanRecord = {tenantId, attemptedAt, accepted: false};
      writeCooldown(record);
      postTabAttempt(tenantId, attemptedAt);
      runScan(providers, {automatic: true});
      writeCooldown({...record, accepted: true});
      void reason;
    };

    if (!scans.length) {
      attempt('bootstrap');
      return;
    }

    if (scan?.status !== 'completed' || !live) return;

    const overviewSettled = !overviewLoading && (!progress || progress.complete);
    const anyRowStale =
      overviewSettled && !!page?.items?.length && page.items.some(row => row.analysis_stale === true);

    if (!anyRowStale) return;
    attempt('stale');
  }, [
    token,
    workspace,
    tenantId,
    canAdmin,
    scanActivity,
    scans,
    scan?.scan_id,
    scan?.status,
    live,
    page?.items,
    overviewLoading,
    progress?.complete,
    planProviders,
    runScan,
  ]);

  return null;
}
