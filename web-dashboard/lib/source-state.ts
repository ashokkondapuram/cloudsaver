import {ApiError} from './api';

export type SourceState<T> =
  | {status: 'loading'}
  | {status: 'success'; data: T; fetchedAt: string}
  | {status: 'forbidden'}
  | {status: 'unavailable'; errorCode: string};

export type SourceOutcome = 'success' | 'forbidden' | 'unavailable' | 'aborted';

export function classifySourceError(error: unknown): SourceOutcome {
  if (error instanceof DOMException && error.name === 'AbortError') return 'aborted';
  if (error instanceof ApiError) {
    if (error.status === 401) return 'aborted';
    if (error.status === 403) return 'forbidden';
    return 'unavailable';
  }
  return 'unavailable';
}

export function errorCodeFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return 'NETWORK_UNAVAILABLE';
    if (error.requestId) return `HTTP_${error.status}`;
    return `HTTP_${error.status}`;
  }
  return 'SOURCE_UNAVAILABLE';
}

export function successState<T>(data: T): SourceState<T> {
  return {status: 'success', data, fetchedAt: new Date().toISOString()};
}

export function unavailableState<T>(error: unknown): SourceState<T> {
  return {status: 'unavailable', errorCode: errorCodeFor(error)};
}

export function anySourceLoading(states: SourceState<unknown>[]): boolean {
  return states.some(s => s.status === 'loading');
}

export function partialSourceFailures(states: SourceState<unknown>[]): boolean {
  return states.some(s => s.status === 'unavailable' || s.status === 'forbidden');
}
