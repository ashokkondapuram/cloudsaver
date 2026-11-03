export const CONTROL_PLANE_PLAN_REVISION_EVENT = 'cloudsaver:cp-plan-revision';

export type ControlPlaneRevisionSource = 'engineering' | 'governance';

export type ControlPlanePlanRevisionDetail = {
  planId?: string;
  at: number;
  source?: ControlPlaneRevisionSource;
};

export function notifyControlPlanePlanRevision(
  planId?: string,
  options?: {source?: ControlPlaneRevisionSource},
) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent<ControlPlanePlanRevisionDetail>(CONTROL_PLANE_PLAN_REVISION_EVENT, {
      detail: {planId, at: Date.now(), source: options?.source ?? 'governance'},
    }),
  );
}

export function subscribeControlPlanePlanRevision(
  handler: (detail: ControlPlanePlanRevisionDetail) => void,
) {
  if (typeof window === 'undefined') return () => {};
  const listener = (event: Event) => {
    const custom = event as CustomEvent<ControlPlanePlanRevisionDetail>;
    handler(custom.detail ?? {at: Date.now(), source: 'governance'});
  };
  window.addEventListener(CONTROL_PLANE_PLAN_REVISION_EVENT, listener);
  return () => window.removeEventListener(CONTROL_PLANE_PLAN_REVISION_EVENT, listener);
}
