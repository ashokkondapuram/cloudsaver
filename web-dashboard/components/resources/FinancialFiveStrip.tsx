'use client';
import {useState} from 'react';
import {api} from '../../lib/api';
import type {FinancialScenarioRequest, FinancialScenarioResponse} from '../../lib/control-plane';
import {money} from '../../lib/finops';
import type {ResourceDetail} from '../../lib/resources';
import {Notice} from '../ui/shared';

type Props = {
  detail: ResourceDetail;
  token: string;
  canAdmin: boolean;
};

function display(value: number | null | undefined, currency = 'USD') {
  return value == null ? 'Unknown' : money(value, currency);
}

export function FinancialFiveStrip({detail, token, canAdmin}: Props) {
  const costs = detail.costs;
  const currency = costs?.currency || 'USD';
  const [absorptionProven, setAbsorptionProven] = useState(false);
  const [scenario, setScenario] = useState<FinancialScenarioResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const avoidableFromScenario =
    scenario?.status === 'computed' && scenario.net_recurring_benefit != null
      ? money(Number(scenario.net_recurring_benefit), scenario.currency || currency)
      : null;

  async function runScenario() {
    if (!canAdmin || costs?.billed_cost_usd == null) return;
    setBusy(true);
    setError('');
    try {
      const baseline = costs.billed_cost_usd.toFixed(2);
      const body: FinancialScenarioRequest = {
        idempotency_key: crypto.randomUUID(),
        currency: currency.length === 3 ? currency : 'USD',
        commitment_fee: costs.effective_cost_usd != null ? costs.effective_cost_usd.toFixed(2) : baseline,
        uncommitted_baseline: baseline,
        uncommitted_if_absorbed: absorptionProven ? '0.00' : baseline,
        absorption_proven: absorptionProven,
        new_recurring: '0',
        one_time: '0',
      };
      const response = await api<FinancialScenarioResponse>('/control-plane/financial-scenarios', token, {
        method: 'POST',
        idempotencyKey: body.idempotency_key,
        body,
      });
      setScenario(response);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const measures = [
    {label: '30-day billed cost', value: display(costs?.billed_cost_usd, currency), sub: 'Payable usage · FOCUS BilledCost window'},
    {label: '30-day effective cost', value: display(costs?.effective_cost_usd, currency), sub: 'Amortized allocation · commitment-aware'},
    {label: 'Retail review estimate', value: display(costs?.retail_estimate_usd ?? detail.assessment.retail_estimate_usd), sub: 'Catalog retail · not billing truth'},
    {
      label: 'Avoidable payable spend',
      value: avoidableFromScenario ?? display(costs?.opportunity_usd, currency),
      sub: absorptionProven ? 'Absorption proven in scenario' : 'Modeled opportunity · do not add overlaps',
      highlight: true,
    },
    {label: 'Verified realized savings', value: display(costs?.verified_realized_savings_usd), sub: 'Finance acceptance required'},
  ];

  return (
    <div className="financial-five-strip panel-bleed" aria-label="Five-measure financial evidence">
      {measures.map(item => (
        <article key={item.label} className={item.highlight ? 'highlight-avoidable' : undefined}>
          <span className="measure-label">{item.label}</span>
          <strong className={item.value === 'Unknown' ? 'metric-unknown measure-value' : 'measure-value'}>{item.value}</strong>
          <small className="measure-sub">{item.sub}</small>
        </article>
      ))}
      {!!detail.financial_overlaps?.length && (
        <div className="overlap-warning-banner panel-bleed" style={{gridColumn: '1 / -1'}}>
          Overlapping alternatives share a workload opportunity group. Do not sum their estimates.
        </div>
      )}
      {canAdmin && costs?.billed_cost_usd != null && (
        <div style={{gridColumn: '1 / -1', display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center'}}>
          <label className="checkbox-row">
            <input type="checkbox" checked={absorptionProven} onChange={e => setAbsorptionProven(e.target.checked)} />
            Absorption proven (released commitment benefit covers eligible usage)
          </label>
          <button type="button" className="button secondary small" disabled={busy} onClick={runScenario}>
            {busy ? 'Computing scenario…' : 'Run commitment-aware scenario'}
          </button>
        </div>
      )}
      {error && (
        <div style={{gridColumn: '1 / -1'}}>
          <Notice tone="error">{error}</Notice>
        </div>
      )}
    </div>
  );
}
