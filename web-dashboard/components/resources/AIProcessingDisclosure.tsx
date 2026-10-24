'use client';
import Link from 'next/link';
import type {Targets} from '../../lib/resources';

export function AIProcessingDisclosure({targets, targetId}: {targets: Targets; targetId: string}) {
  const target = targets.targets.find(item => item.target_id === targetId);
  if (!target) return <p className="inline-help">{targets.configuration_reason || 'No approved destination matches this resource.'} <Link href="/settings/ai">Configure AI Foundry</Link></p>;
  return <div className="drawer-section" aria-label="AI processing disclosure">
    <strong>Review the destination before requesting inference</strong>
    <dl className="settings-key-values"><div><dt>Provider and model</dt><dd>{target.provider} · {target.model}</dd></div>
      <div><dt>Destination region</dt><dd>{target.destination_region || 'Unspecified — verify with the operator'}</dd></div>
      <div><dt>Permitted source providers</dt><dd>{target.allowed_source_providers?.join(', ') || 'Not disclosed'}</dd></div>
      <div><dt>Published knowledge retrieval</dt><dd>{targets.knowledge_retrieval || 'Not disclosed'} (availability checked at request time)</dd></div>
      <div><dt>Remaining hourly attempts at last refresh</dt><dd>{targets.usage ? Math.max(0, targets.hourly_attempt_limit - targets.usage.attempts_current_hour) : 'Unknown'}</dd></div></dl>
    <p className="inline-help">Input contains check codes, statuses and allowlisted saved facts. Names, resource IDs and raw tags are excluded. Follow-up questions are sent as entered. Model advice remains unverified; provider retention settings need independent review.</p>
  </div>;
}
