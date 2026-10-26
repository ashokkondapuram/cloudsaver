import {test, expect} from './test';
import {opportunityTotals} from '../lib/finops';
import type {Finding} from '../lib/types';

const finding = (resource_id: string, amount: number | null, group?: string): Finding => ({resource_id,
  rule_id: 'ORPHANED_DISK', severity: 'LOW', resource_name: resource_id, resource_type: 'disk', resource_group: 'fixture',
  subscription_id: 'fixture', estimated_monthly_waste_usd: amount, details: 'Synthetic fixture', opportunity_group_id: group});

test('connected workload alternatives contribute their maximum, with unknown totals kept separate', () => {
  expect(opportunityTotals([finding('vm', 100, 'workload'), finding('disk', 40, 'workload'), finding('other', 10)]))
    .toEqual({known: 110, total: 110, overlapping_groups: 1, unpriced_groups: 0});
  expect(opportunityTotals([finding('vm', 100, 'workload'), finding('disk', null, 'workload')]))
    .toEqual({known: 100, total: null, overlapping_groups: 1, unpriced_groups: 1});
  expect(opportunityTotals([finding('free', 0)])).toMatchObject({total: 0, known: 0});
});
