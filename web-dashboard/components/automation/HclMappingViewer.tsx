'use client';

import {useEffect, useState} from 'react';
import {api} from '../../lib/api';

type Mapping = {
  cloud_resource_id: string;
  repository: string;
  file_path: string;
  iac_kind: string;
  start_line: number | null;
  end_line: number | null;
  indexed_commit_sha: string | null;
  address: string | null;
};

export function HclMappingViewer({token, resourceId}: {token: string; resourceId: string | null}) {
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const c = new AbortController();
    setMapping(null);
    setError('');
    if (!resourceId) return () => c.abort();
    api<Mapping>('/gitops/resource-mapping?resource_id=' + encodeURIComponent(resourceId), token, {signal: c.signal})
      .then(v => {
        if (!c.signal.aborted) setMapping(v);
      })
      .catch(e => {
        if (!c.signal.aborted) setError((e as Error).message);
      });
    return () => c.abort();
  }, [token, resourceId]);

  if (!resourceId) return null;
  if (error) return <p className="inline-help">AST index: {error}</p>;
  if (!mapping) return <p className="inline-help">Loading AST resource mapping…</p>;

  const lines = [
    `# ${mapping.file_path}`,
    `# ${mapping.iac_kind} · ${mapping.repository}`,
    mapping.address ? `resource "${mapping.address.split('.').slice(-1)[0]}" {` : 'resource "indexed" {',
    `  # lines ${mapping.start_line ?? '?'}–${mapping.end_line ?? '?'} @ ${mapping.indexed_commit_sha?.slice(0, 7) ?? 'unknown'}`,
    '  # surgical diff preview — repository CI must validate the real plan',
    '}',
  ];

  return (
    <div className="hcl-diff-container" aria-label="AST HCL mapping">
      <div className="hcl-diff-header">
        <span>{mapping.file_path}</span>
        <span>
          {mapping.start_line}–{mapping.end_line}
        </span>
      </div>
      <pre className="hcl-diff-pre">
        {lines.map((line, i) => (
          <code key={i} className={`hcl-line ${i === 2 ? 'added' : ''}`}>
            {line}
          </code>
        ))}
      </pre>
    </div>
  );
}
