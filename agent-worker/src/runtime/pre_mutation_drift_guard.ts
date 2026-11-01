import type {Task} from './contracts.ts';

export function assertPermitNotDriftAborted(task: Task): void {
  const status = task.payload?.permit_status;
  if (status === 'ABORTED_STATE_DRIFT') {
    throw new Error('ABORTED_STATE_DRIFT');
  }
}

export function assertExpectedStatePresent(task: Task, writeStep: boolean): void {
  if (writeStep && !task.payload?.expected_state) {
    throw new Error('EXPECTED_STATE_REQUIRED');
  }
}
