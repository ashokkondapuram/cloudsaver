import assert from 'node:assert/strict';
import {agentInFlightCount, gitopsOpenCount, observabilityIssueCount, taskStateCounts} from '../lib/action-center-metrics.ts';
import {classifySourceError} from '../lib/source-state.ts';

assert.equal(gitopsOpenCount([{status: 'open'}, {status: 'closed'}]), 1);
assert.equal(agentInFlightCount(taskStateCounts([{state: 'running'}, {state: 'resolved'}])), 1);
assert.equal(observabilityIssueCount([{id: '1', status: 'healthy'}, {id: '2', status: 'degraded'}]), 1);
assert.equal(classifySourceError(new TypeError('network')), 'unavailable');

console.log('action-center-sources ok');
