import assert from 'node:assert/strict';
import {billingDailyToChartSeries, finopsPeriodLabel} from '../lib/finops-chart.ts';
import {validateChartSeries} from '../lib/atlas-contracts.ts';

const series = billingDailyToChartSeries(
  {
    currency: 'USD',
    daily: [
      {date: '2026-10-01', billed_cost: '10.5', complete: true},
      {date: '2026-10-02', billed_cost: null, complete: false},
      {date: '2026-10-03', billed_cost: '12', complete: true},
    ],
  },
  {start: '2026-10-01', end: '2026-10-04'},
);

assert.equal(series.currency, 'USD');
assert.equal(series.status, 'partial');
assert.equal(series.points.length, 3);
assert.equal(series.points[1].value, null);
assert.equal(validateChartSeries(series), null);
assert.match(finopsPeriodLabel('2026-10-01', '2026-10-04'), /2026-10-01/);

console.log('finops-chart tests ok');
