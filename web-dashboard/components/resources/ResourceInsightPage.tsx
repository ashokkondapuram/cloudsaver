'use client';
import Link from 'next/link';
import {useMemo} from 'react';
import {useSearchParams} from 'next/navigation';
import {ArrowLeft, ComputerTower} from '@phosphor-icons/react';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState, Loading, Notice} from '../ui/shared';
import {isLiveSnapshot} from '../../lib/resources';
import {resourceListHref} from '../../lib/resource-insight';
import {ResourceInsightView} from './ResourceDrawer';

export function ResourceInsightPage() {
  const params = useSearchParams();
  const {scans, token, busy} = useWorkspace();
  const urlScanId = params.get('scan_id') || '';
  const resourceKey = params.get('resource') || '';
  const provider = params.get('provider') || '';
  const resourceId = params.get('resource_id') || '';
  const identity = useMemo(
    () => (provider && resourceId ? {provider, resourceId} : null),
    [provider, resourceId],
  );

  const insightScan = urlScanId ? scans.find(s => s.scan_id === urlScanId) : scans[0];
  const scanId = insightScan?.scan_id || urlScanId || '';

  if (!resourceKey) {
    return <EmptyState icon={ComputerTower} title="No resource selected">Choose a resource from the Resources list.</EmptyState>;
  }

  if (token && !scans.length) {
    if (busy) return <Loading label="Loading workspace snapshots…"/>;
    return <EmptyState icon={ComputerTower} title="No scan available">Wait for your workspace snapshot to finish, or open Resources after a tenant admin has triggered collection.</EmptyState>;
  }

  if (urlScanId && scans.length && !scans.some(s => s.scan_id === urlScanId)) {
    return (
      <Notice tone="warning">
        This insight link references a scan that is not in your workspace.{' '}
        <Link className="text-link" href="/resources">Open Resources</Link>
      </Notice>
    );
  }

  if (!scanId || !insightScan) {
    return <EmptyState icon={ComputerTower} title="No scan selected">Pick a scan on the Resources page, or return from a resource link once a snapshot exists.</EmptyState>;
  }

  if (!isLiveSnapshot(insightScan)) {
    return <EmptyState icon={ComputerTower} title="A live scan is required">Resource insights use saved observations from a completed or in-progress live scan.</EmptyState>;
  }

  return (
    <div className="resource-insight-page">
      <div className="page-heading">
        <h1>Resource insight</h1>
        <Link className="button secondary" href={resourceListHref(resourceKey, identity)}>
          <ArrowLeft size={16} weight="regular"/> Back to resources
        </Link>
      </div>
      <ResourceInsightView
        scanId={scanId}
        resourceKey={resourceKey}
        identity={identity}
        layout="page"
        onClose={() => {}}
        onChange={() => {}}
      />
    </div>
  );
}
