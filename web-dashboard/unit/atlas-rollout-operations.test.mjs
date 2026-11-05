import assert from 'node:assert/strict';
import {aiUsageToChartSeries, deliveryCountsToChartSeries} from '../lib/operations-chart.ts';
import {validateChartSeries} from '../lib/atlas-contracts.ts';
import {ATLAS_PAGE_ROLLOUT, atlasRolloutComplete, atlasRolloutForRoute} from '../lib/atlas-page-rollout.ts';

const delivery = deliveryCountsToChartSeries([
  {kind: 'notification', status: 'pending', count: 2},
  {kind: 'scan', status: 'dead_letter', count: 1},
]);
assert.equal(delivery.points.find(p => p.timestamp === 'pending')?.value, 2);
assert.equal(validateChartSeries(delivery), null);

const ai = aiUsageToChartSeries([{attempts: 10, completed: 7, incomplete_outcomes: 3}]);
assert.equal(ai.status, 'complete');
assert.equal(ai.points[0].value, 10);

assert.ok(atlasRolloutForRoute('/governance')?.label.includes('compliance'));
assert.ok(atlasRolloutForRoute('/services/disks'));
assert.equal(atlasRolloutComplete(), true);
assert.equal(ATLAS_PAGE_ROLLOUT.length >= 15, true);

console.log('operations-chart + rollout tests ok');
