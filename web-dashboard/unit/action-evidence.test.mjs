import assert from 'node:assert/strict';
import test from 'node:test';
import {actionEvidenceFromResource} from '../lib/control-plane.ts';

test('actionEvidenceFromResource sends null for every unobserved field', () => {
  const evidence = actionEvidenceFromResource({
    assessment: {disposition: 'eligible', protected_reasons: [], resource_id: 'r1'},
  });
  assert.equal(evidence.claims_positive_benefit, false);
  assert.equal(evidence.absorption_proven, null);
  assert.equal(evidence.fees_remain, null);
  assert.equal(evidence.ip_dependency_confirmed, null);
  assert.equal(evidence.external_owner_known, null);
  assert.equal(evidence.removes_quorum_member, null);
  assert.equal(evidence.violates_capacity_floor, null);
  assert.equal(evidence.is_standby_or_replica, null);
  assert.equal(evidence.active_hold, null);
  assert.equal(evidence.destructive, null);
  assert.equal(evidence.restore_verified, null);
  assert.equal(evidence.capacity_reduction, null);
  assert.equal(evidence.memory_history_days, null);
  assert.equal(evidence.valid_sample_ratio, null);
  assert.equal(evidence.insufficient_headroom, null);
  assert.equal(evidence.owner, null);
  assert.equal(evidence.responder_reachable, null);
  assert.equal(evidence.rollback_supported, null);
});

test('actionEvidenceFromResource derives memory window and ratio only from observed server evidence', () => {
  const evidence = actionEvidenceFromResource({
    assessment: {disposition: 'eligible', protected_reasons: [], resource_id: 'r1'},
    observation: {evidence: {
      metrics: {memory_util: {window_start: '2026-10-01T00:00:00Z', window_end: '2026-10-31T00:00:00Z'}},
      metric_summaries: {memory_util: {coverage_ratio: 0.99}},
    }},
  });
  assert.equal(evidence.memory_history_days, 30);
  assert.equal(evidence.valid_sample_ratio, 0.99);
});
