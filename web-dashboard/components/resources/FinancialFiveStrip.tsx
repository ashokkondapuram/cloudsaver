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
  /** When true, hide measures with no value instead of five Unknown cards. */
  knownOnly?: boolean;
};

function display(value: number | null | undefined, currency = 'USD') {
  return value == null ? 'Unknown' : money(value, currency);
}

export function FinancialFiveStrip({detail, token, canAdmin, knownOnly = false}: Props) {
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

  const retailRun = costs?.retail_run_rate_usd ?? costs?.retail_estimate_usd ?? detail.assessment.retail_estimate_usd;
  const wasteOpp = costs?.retail_waste_opportunity_usd ?? costs?.opportunity_usd;
  const billedVsRetail = costs?.billed_vs_retail_usd;
  const listSavings = costs?.retail_list_savings_usd;
  const commitmentBenefit = costs?.commitment_benefit_usd;
  const payableReduction = costs?.modeled_payable_reduction_usd;

  const balanceSub =
    billedVsRetail == null
      ? 'Needs billed import and Azure retail meters'
      : billedVsRetail > 0
        ? 'Billed above Azure list in this window'
        : billedVsRetail < 0
          ? 'Billed below Azure list (discount or mismatch)'
          : 'Billed matches Azure list run-rate';

  const measures = [
    {label: '30-day billed cost', value: display(costs?.billed_cost_usd, currency), sub: 'Payable usage · FOCUS / Cost Management', known: costs?.billed_cost_usd != null},
    {label: '30-day effective cost', value: display(costs?.effective_cost_usd, currency), sub: 'Amortized allocation · commitment-aware', known: costs?.effective_cost_usd != null},
    {
      label: 'Azure retail run-rate',
      value: display(retailRun),
      sub: 'Catalog list price · USD / month equivalent',
      known: retailRun != null,
    },
    {
      label: 'Billed vs retail balance',
      value: display(billedVsRetail, currency),
      sub: balanceSub,
      known: billedVsRetail != null,
    },
    {
      label: 'Discount vs Azure list',
      value: display(listSavings, currency),
      sub: 'Retail run-rate minus billed (positive = paying below list)',
      known: listSavings != null && listSavings !== 0,
    },
    {
      label: 'Commitment benefit',
      value: display(commitmentBenefit, currency),
      sub: 'Billed minus effective (reservations / amortization)',
      known: commitmentBenefit != null && commitmentBenefit !== 0,
    },
    {
      label: 'Retail-modeled waste',
      value: display(wasteOpp),
      sub: costs?.retail_waste_opportunity_incomplete ? 'Partial overlap rollup · do not sum groups' : 'Finding waste from Azure retail meters',
      highlight: true,
      known: wasteOpp != null,
    },
    {
      label: 'Modeled payable reduction',
      value: display(payableReduction, currency),
      sub: 'Conservative min(billed, retail waste) · not verified savings',
      known: payableReduction != null,
    },
    {
      label: 'Avoidable (scenario)',
      value: avoidableFromScenario ?? display(null, currency),
      sub: absorptionProven ? 'Absorption proven in scenario' : 'Run scenario when billed is known',
      known: avoidableFromScenario != null,
    },
    {label: 'Verified realized savings', value: display(costs?.verified_realized_savings_usd), sub: 'Finance acceptance required', known: costs?.verified_realized_savings_usd != null},
  ];
  const visible = knownOnly ? measures.filter(item => item.known) : measures;

  if (knownOnly && !visible.length) {
    return (
      <Notice>
        No billed, retail, or savings evidence is attached yet. Fetch billing on this tab or run a scan with verified retail meters.
      </Notice>
    );
  }

  return (
    <div className="financial-five-strip panel-bleed" aria-label="Five-measure financial evidence">
      {visible.map(item => (
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
