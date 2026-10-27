'use client';

import Link from 'next/link';
import {useWorkspace} from './WorkspaceProvider';

export function WorkspaceContext() {
  const {workspace, scan, scope} = useWorkspace();
  if (!workspace) return null;
  const timestamp = scan && Number.isFinite(Date.parse(scan.timestamp)) ? new Date(scan.timestamp).toISOString() : null;
  return <section className="workspace-evidence-context" aria-label="Current evidence context">
    <div><span>Workspace</span><strong>{workspace.name}</strong></div>
    <div><span>Resource observation · UTC</span>{timestamp ? <time dateTime={timestamp}>{timestamp.replace('T', ' ').replace('.000Z', ' UTC')}</time> : <strong>No snapshot selected</strong>}</div>
    <div><span>Resource scope</span><strong>{scope.length ? `${scope.length} selected` : 'All authorized scan scopes'}</strong></div>
    <Link href="/allocation" className="text-link">Billing has its own period →</Link>
  </section>;
}
