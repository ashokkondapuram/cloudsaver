import assert from 'node:assert/strict';
import {nextPollDelayMs, phaseAfterSubmission, shouldContinuePolling} from '../lib/scan-lifecycle.ts';

assert.equal(nextPollDelayMs(0), 8000);
assert.equal(nextPollDelayMs(2), 32000);
assert.equal(shouldContinuePolling('reconciling'), true);
assert.equal(shouldContinuePolling('idle'), false);
assert.equal(phaseAfterSubmission('running', false), 'running');
assert.equal(phaseAfterSubmission(undefined, true), 'reconciling');

console.log('scan-lifecycle ok');
