export type ArmDetailStatus = 'collected' | 'unsupported_type' | 'resource_budget_exceeded' | 'api_version_unresolved' | 'fetch_failed';

export const ARM_DETAIL_STATUSES: ArmDetailStatus[] = ['collected', 'unsupported_type', 'resource_budget_exceeded', 'api_version_unresolved', 'fetch_failed'];

export const armDetailLabels: Record<ArmDetailStatus, string> = {
  collected: 'ARM detail collected',
  unsupported_type: 'Unsupported ARM type',
  resource_budget_exceeded: 'ARM detail budget exceeded',
  api_version_unresolved: 'ARM API version unresolved',
  fetch_failed: 'ARM detail fetch failed',
};

export function armDetailFromQuery(value: string | null | undefined): ArmDetailStatus | '' {
  return typeof value === 'string' && ARM_DETAIL_STATUSES.includes(value as ArmDetailStatus) ? value as ArmDetailStatus : '';
}
