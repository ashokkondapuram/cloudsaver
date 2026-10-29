import {test} from 'node:test';
import assert from 'node:assert/strict';
import {healthState} from '../src/health.ts';

test('health separates progress, readiness, stalled work and shutdown', () => {
  let now = 0;
  const state = healthState(() => now);
  assert.equal(state.status('/health/live').code, 200);
  assert.equal(state.status('/health/ready').code, 503);
  state.touch();
  assert.equal(state.status('/health/ready').code, 200);
  state.touch(false);
  assert.equal(state.status('/health/live').code, 200);
  assert.equal(state.status('/health/ready').code, 503);
  now = 120001;
  assert.equal(state.status('/health/live').code, 503);
  state.touch(); state.stop();
  assert.equal(state.status('/health/live').code, 503);
  assert.equal(state.status('/missing').code, 404);
});
