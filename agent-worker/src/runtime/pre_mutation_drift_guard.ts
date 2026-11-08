import type {Task} from '../contracts.ts';

export function assertPermitNotDriftAborted(task: Task): void {
  const status = task.payload?.permit_status;
  if (status === 'ABORTED_STATE_DRIFT') {
    throw new Error('ABORTED_STATE_DRIFT');
  }
}

function nonEmptyObject(value: unknown): boolean {
  return !!value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length > 0;
}

export function assertExpectedStatePresent(task: Task, writeStep: boolean): void {
  if (!writeStep) return;
  const taskExpected = task.payload?.expected_state;
  const inspectStep = task.payload?.plan?.steps?.[0];
  const stepExpected = inspectStep?.arguments?.expected_state;
  // Both the server-captured baseline and the plan's own inspect-step baseline must be
  // present and non-empty: an empty {} previously passed this check (it is defined, just
  // vacuous), letting a write proceed with nothing actually compared against live state.
  if (!nonEmptyObject(taskExpected) || !nonEmptyObject(stepExpected)) {
    throw new Error('EXPECTED_STATE_REQUIRED');
  }
}
