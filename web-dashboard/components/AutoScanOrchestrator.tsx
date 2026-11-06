'use client';

import {useEffect, useRef} from 'react';
import {isLiveSnapshot, useResources} from '../lib/resources';
import {useWorkspace} from './WorkspaceProvider';

/** Avoid tight loops if the API keeps reporting stale rows. */
const MIN_AUTO_INTERVAL_MS = 10 * 60 * 1000;

/**
 * Starts a multi-cloud inventory scan when there is no snapshot yet, or when
 * the overview resource rows include `analysis_stale` (per-resource staleness).
 * Tenant admins only.
 */
export function AutoScanOrchestrator() {
  const {token, workspace, scans, scan, canAdmin, scanActivity, planProviders, runScan, liveScanEpoch} = useWorkspace();
  const live = isLiveSnapshot(scan);
  const inProgress = scan?.status === 'running';
  const {page, loading: overviewLoading, progress} = useResources(scan?.scan_id, token, live && !!scan?.scan_id, inProgress ? liveScanEpoch : 0, {
    running: inProgress,
    overview: !inProgress,
  });

  const lastAutoScanAt = useRef(0);

  useEffect(() => {
    if (!token || !workspace || !canAdmin) return;
    if (scanActivity) return;
    if (scans.some(s => s.status === 'running')) return;

    const providers = planProviders(workspace.allowed_providers ?? workspace.providers ?? ['azure']).filter(Boolean);
    if (!providers.length) return;

    if (!scans.length) {
      const now = Date.now();
      if (now - lastAutoScanAt.current < MIN_AUTO_INTERVAL_MS) return;
      lastAutoScanAt.current = now;
      runScan(providers, {automatic: true});
      return;
    }

    if (scan?.status !== 'completed' || !live) return;

    const overviewSettled = !overviewLoading && (!progress || progress.complete);
    const anyRowStale =
      overviewSettled && !!page?.items?.length && page.items.some(row => row.analysis_stale === true);

    if (!anyRowStale) return;

    const now = Date.now();
    if (now - lastAutoScanAt.current < MIN_AUTO_INTERVAL_MS) return;
    lastAutoScanAt.current = now;
    runScan(providers, {automatic: true});
  }, [
    token,
    workspace,
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
