'use client';

import {useEffect, useState} from 'react';
import {TerminalWindow} from '@phosphor-icons/react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

type Status = {
  enabled: boolean;
  bridge_configured: boolean;
  bridge_host: string | null;
  runtime: string;
  max_snippet_bytes: number;
  stub_mode: boolean;
};

type Run = {
  id: string;
  state: string;
  version: number;
  snippet_digest: string;
  payload: {input: Record<string, unknown>};
  result: {status?: string; output?: unknown; error?: string} | null;
  created_at: string;
  updated_at: string;
};

const DEFAULT_SNIPPET = `function transform(input) {
  return { echoed: true, keys: Object.keys(input || {}) };
}`;

export function CodeModePanel() {
  const {token, canAdmin, workspace} = useWorkspace();
  const human = workspace?.subject_type === 'user' && !workspace?.key_id;
  const [status, setStatus] = useState<Status | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [snippet, setSnippet] = useState(DEFAULT_SNIPPET);
  const [inputJson, setInputJson] = useState('{\n  "sample": "value"\n}');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<Run | null>(null);

  useEffect(() => {
    const request = new AbortController();
    setStatus(null);
    setRuns([]);
    setError('');
    if (!token) return () => request.abort();
    Promise.all([
      api<Status>('/code-mode/status', token, {signal: request.signal}),
      api<{items: Run[]}>('/code-mode/runs', token, {signal: request.signal}),
    ])
      .then(([value, list]) => {
        if (!request.signal.aborted) {
          setStatus(value);
          setRuns(list.items || []);
        }
      })
      .catch(cause => {
        if (!request.signal.aborted) setError((cause as Error).message);
      });
    return () => request.abort();
  }, [token]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canAdmin || !human || !status?.enabled) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const input = JSON.parse(inputJson) as Record<string, unknown>;
      const run = await api<Run>('/code-mode/runs', token, {
        body: {
          request_key: crypto.randomUUID(),
          snippet,
          input,
          acknowledge_sandbox: ack,
        },
      });
      setRuns(old => [run, ...old.filter(r => r.id !== run.id)]);
      setSelected(run);
      setNotice(`Run ${run.id.slice(0, 8)} completed with state ${sentence(run.state)}.`);
      setAck(false);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const ready = status?.enabled && status.bridge_configured;

  return (
    <section className="panel code-mode-panel" data-atlas-rollout="code-mode">
      <SectionTitle eyebrow="CODE MODE" title="Managed execution sandbox">
        Isolated JavaScript transforms via your operator&apos;s Cloudflare Worker bridge.
      </SectionTitle>
      {error && <Notice tone="error">{error}</Notice>}
      {notice && <Notice tone="success">{notice}</Notice>}
      {!status && !error ? (
        <Loading label="Loading Code Mode status…"/>
      ) : status && !status.enabled ? (
        <Notice tone="warning">Code Mode is disabled for this deployment. Set CLOUDSAVER_CODE_MODE_ENABLED on the scanner service.</Notice>
      ) : status && !status.bridge_configured ? (
        <Notice tone="warning">Code Mode is enabled but the worker bridge is not configured. Deploy workers/code-mode-bridge and set CLOUDFLARE_CODE_MODE_BRIDGE_URL.</Notice>
      ) : (
        <>
          <p className="inline-help">
            Runtime {status?.runtime}
            {status?.bridge_host ? ` · bridge ${status.bridge_host}` : ''}
            {status?.stub_mode ? ' · stub executor (non-production)' : ''}
          </p>
          {!canAdmin || !human ? (
            <Notice tone="info">A verified human workspace administrator can submit sandbox runs.</Notice>
          ) : (
            <form className="code-mode-form" onSubmit={submit}>
              <label>
                transform(input) snippet
                <textarea
                  rows={8}
                  required
                  value={snippet}
                  maxLength={status?.max_snippet_bytes}
                  onChange={e => setSnippet(e.target.value)}
                />
              </label>
              <label>
                Input JSON
                <textarea rows={4} required value={inputJson} onChange={e => setInputJson(e.target.value)}/>
              </label>
              <label className="agent-check">
                <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>
                <span>I accept that this snippet runs in an isolated worker boundary separate from agent connector execution.</span>
              </label>
              <button className="button primary" type="submit" disabled={busy || !ack || !ready}>
                <TerminalWindow size={16} weight="regular"/>
                {busy ? 'Running…' : 'Run in sandbox'}
              </button>
            </form>
          )}
          {runs.length ? (
            <div className="code-mode-history">
              <h3>Recent runs</h3>
              <ul>
                {runs.map(run => (
                  <li key={run.id}>
                    <button type="button" className="code-mode-run" aria-pressed={selected?.id === run.id} onClick={() => setSelected(run)}>
                      <strong>{run.id.slice(0, 8)}</strong>
                      <span>{sentence(run.state)}</span>
                      <small>{dateTime(run.created_at)}</small>
                    </button>
                  </li>
                ))}
              </ul>
              {selected && (
                <div className="code-mode-result" aria-live="polite">
                  <p>
                    Digest <code>{selected.snippet_digest.slice(0, 16)}</code> · {sentence(selected.state)}
                  </p>
                  <pre>{JSON.stringify(selected.result, null, 2)}</pre>
                </div>
              )}
            </div>
          ) : (
            <EmptyState icon={TerminalWindow} title="No sandbox runs yet">Approved transforms and outcomes are retained for audit.</EmptyState>
          )}
        </>
      )}
    </section>
  );
}
