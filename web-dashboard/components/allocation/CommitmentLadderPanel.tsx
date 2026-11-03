'use client';

import {useEffect, useState} from 'react';
import {api} from '../../lib/api';
import {useWorkspace} from '../WorkspaceProvider';
import {Notice} from '../ui/shared';

type LadderStep = {step_pct: string; quarter: number; recommended_new_commitment_hr: string; purchase_authorized: boolean; status: string; ladder_note: string};

export function CommitmentLadderPanel({currency = 'USD'}: {currency?: string}) {
  const {token, canBill} = useWorkspace();
  const [raw, setRaw] = useState('10.0000');
  const [waste, setWaste] = useState('2.0000');
  const [existing, setExisting] = useState('1.0000');
  const [data, setData] = useState<{steps: LadderStep[]; purchase_authorized: boolean} | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setData(null);
  }, [token]);

  if (!canBill) return null;

  async function preview() {
    setBusy(true);
    setError('');
    try {
      const qs = new URLSearchParams({raw_p10_hr: raw, waste_hr: waste, existing_hr: existing}).toString();
      const value = await api<{steps: LadderStep[]; purchase_authorized: boolean}>(
        '/finops/commitment-ladder/preview?' + qs,
        token,
      );
      setData(value);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel commitment-ladder-panel">
      <h3>Commitment ladder (scenario only)</h3>
      <p className="inline-help">
        Staggered 25/50/75% planning steps from a clean hourly baseline. purchase_authorized remains false; no purchase API is
        invoked.
      </p>
      <div className="enterprise-filters">
        <label>
          Raw P10 spend / hr ({currency})
          <input value={raw} onChange={e => setRaw(e.target.value)} pattern="^\d+(\.\d+)?$" />
        </label>
        <label>
          Open waste / hr
          <input value={waste} onChange={e => setWaste(e.target.value)} />
        </label>
        <label>
          Existing commitments / hr
          <input value={existing} onChange={e => setExisting(e.target.value)} />
        </label>
        <button type="button" className="button secondary" disabled={busy} onClick={preview}>
          {busy ? 'Computing…' : 'Preview ladder'}
        </button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {data && (
        <>
          <Notice tone="warning">purchase_authorized: {String(data.purchase_authorized)}</Notice>
          <div className="commitment-ladder-grid">
            {data.steps.map(step => (
              <article key={step.quarter}>
                <span className="measure-label">Q{step.quarter} · {step.step_pct}% tranche</span>
                <strong className="measure-value">{step.recommended_new_commitment_hr} / hr</strong>
                <small className="measure-sub">{step.ladder_note}</small>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export function expiryBadge(end: string | null) {
  if (!end) return null;
  const days = Math.ceil((Date.parse(end.slice(0, 10) + 'T12:00:00Z') - Date.now()) / 86400000);
  if (days < 0) return <span className="state-badge expired">Expired</span>;
  const thresholds = [90, 60, 30] as const;
  const within = thresholds.filter(t => days <= t);
  const hit = within.length ? Math.min(...within) : null;
  if (hit == null) return null;
  return <span className={`state-badge expiry-${hit}`}>{hit}-day expiry</span>;
}
