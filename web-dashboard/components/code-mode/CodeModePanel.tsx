'use client';

import {TerminalSquare} from 'lucide-react';
import {EmptyState, Notice, SectionTitle} from '../ui/shared';

/**
 * Cloudflare Code Mode placeholder — execution stays disabled until product
 * verifies Cloudflare bindings, egress policy, and tenant consent.
 */
export function CodeModePanel() {
  return (
    <section className="panel code-mode-panel" data-atlas-rollout="code-mode">
      <SectionTitle eyebrow="CODE MODE" title="Managed execution sandbox">
        Cloudflare Code Mode is not configured for this workspace.
      </SectionTitle>
      <Notice tone="info">
        Code Mode would run operator-approved snippets inside an isolated worker boundary. CloudSaver does not ship Cloudflare credentials or live execution until your platform team completes integration review.
      </Notice>
      <EmptyState icon={TerminalSquare} title="Execution unavailable">
        Read-only governance and agent connector flows remain unchanged. When Code Mode is enabled, approved plans may reference sandboxed transforms here with full audit retention.
      </EmptyState>
    </section>
  );
}
