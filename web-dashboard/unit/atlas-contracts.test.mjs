import assert from 'node:assert/strict';
import test from 'node:test';
import {validateChartSeries} from '../lib/atlas-contracts.ts';

test('validateChartSeries rejects non-finite values', () => {
  const err = validateChartSeries({
    id: 'spend',
    label: 'Spend',
    unit: 'USD',
    status: 'complete',
    observedAt: '2026-11-01T00:00:00Z',
    points: [{timestamp: '2026-11-01', value: Number.NaN}],
  });
  assert.equal(err, 'Series points must be finite numbers or null gaps.');
});

test('validateChartSeries accepts null gaps', () => {
  assert.equal(
    validateChartSeries({
      id: 'spend',
      label: 'Spend',
      unit: 'USD',
      status: 'partial',
      observedAt: null,
      points: [{timestamp: '2026-11-01', value: null}, {timestamp: '2026-11-02', value: 12.5}],
    }),
    null,
  );
});
