export const CONTROL_PLANE_PLAN_REVISION_EVENT = 'cloudsaver:cp-plan-revision';

export function notifyControlPlanePlanRevision(planId?: string) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(CONTROL_PLANE_PLAN_REVISION_EVENT, {detail: {planId, at: Date.now()}}));
}

export function subscribeControlPlanePlanRevision(onRevision: () => void) {
  if (typeof window === 'undefined') return () => {};
  const handler = () => onRevision();
  window.addEventListener(CONTROL_PLANE_PLAN_REVISION_EVENT, handler);
  return () => window.removeEventListener(CONTROL_PLANE_PLAN_REVISION_EVENT, handler);
}
