import type {Task} from '../contracts.ts';

export function assertPermitNotDriftAborted(task: Task): void {
  const status = task.payload?.permit_status;
  if (status === 'ABORTED_STATE_DRIFT') {
    throw new Error('ABORTED_STATE_DRIFT');
  }
}

export function assertExpectedStatePresent(task: Task, writeStep: boolean): void {
  if (!writeStep) return;
  const taskExpected = task.payload?.expected_state;
  const stepExpected = task.payload?.plan?.steps?.[0]?.arguments?.expected_state;
  if (taskExpected === null || (taskExpected === undefined && stepExpected === undefined)) {
    throw new Error('EXPECTED_STATE_REQUIRED');
  }
}
