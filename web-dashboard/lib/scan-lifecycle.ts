export type ScanLifecyclePhase = 'idle' | 'submitting' | 'running' | 'reconciling' | 'failed';

export const POLL_BASE_MS = 8000;
export const POLL_MAX_MS = 60_000;

export function nextPollDelayMs(failures: number): number {
  if (failures <= 0) return POLL_BASE_MS;
  return Math.min(POLL_MAX_MS, POLL_BASE_MS * 2 ** Math.min(failures, 3));
}

export function shouldContinuePolling(phase: ScanLifecyclePhase): boolean {
  return phase === 'submitting' || phase === 'running' || phase === 'reconciling';
}

export function phaseAfterSubmission(status: string | undefined, uncertain: boolean): ScanLifecyclePhase {
  if (uncertain) return 'reconciling';
  if (status === 'running') return 'running';
  if (status === 'completed') return 'idle';
  if (status === 'failed' || status === 'cancelled') return 'failed';
  return 'reconciling';
}

export function phaseFromHistory(hasRunning: boolean, submitting: boolean): ScanLifecyclePhase {
  if (hasRunning) return 'running';
  if (submitting) return 'reconciling';
  return 'idle';
}
